"""
Postman Collection v2.1 parser.
Validates and flattens collection items into a list of ParsedRequest objects.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, field_validator
from unidecode import unidecode

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# Guards against a malformed (or hand-crafted) collection whose folders nest so
# deeply that recursion would overflow the stack. Real Postman folder trees are
# only a handful of levels deep, so this ceiling is well above any genuine use.
_MAX_FOLDER_DEPTH = 100


def _replace_vars(value: str) -> str:
    """Replace Postman {{variable}} with Python os.environ placeholder."""
    return _VAR_RE.sub(r"ENV_\1", value)


def _slugify(text: str) -> str:
    """
    Convert arbitrary text into an ASCII-safe pytest identifier fragment.

    Non-ASCII characters (Cyrillic, Chinese, Arabic, accented Latin, etc.)
    are transliterated to closest ASCII via unidecode. The result is then
    lowercased and stripped of non-alphanumerics. Returns 'unnamed' for
    empty input or input that yields no usable characters.
    """
    if not text:
        return "unnamed"
    ascii_text = unidecode(text)
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or "unnamed"


_STATUS_HAVE_RE = re.compile(r"\.have\.status\((\d+)\)")
_STATUS_CODE_RE = re.compile(r"pm\.response\.code\s*===?\s*(\d+)")


def _extract_status(events: list[dict[str, Any]]) -> int | None:
    """
    Try to extract expected status code from Postman test scripts.

    Recognises both common idioms:
      - pm.response.to.have.status(201)
      - pm.response.code === 201   (also the loose == form)
    The .have.status(N) form wins when both appear in one script.
    """
    for event in events:
        if event.get("listen") != "test":
            continue
        script = "\n".join(event.get("script", {}).get("exec", []))
        match = _STATUS_HAVE_RE.search(script) or _STATUS_CODE_RE.search(script)
        if match:
            return int(match.group(1))
    return None


def _parse_js_value(raw: str) -> Any:
    """
    Parse a JS literal (string, number, boolean) into its Python value.

    Returns None when the token is not a recognised literal (for example a
    variable reference or an expression). None signals the caller to skip the
    assertion rather than emit a guess.
    """
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return None


_RESP_TIME_RE = re.compile(r"responseTime\s*\)\s*\.to\.be\.below\(\s*(\d+)\s*\)")
_HEADER_RE = re.compile(r"\.to\.have\.header\(\s*(['\"])(.+?)\1\s*\)")
_JSON_FIELD_RE = re.compile(
    r"pm\.expect\(\s*(?:jsonData|pm\.response\.json\(\))\.(\w+)\s*\)"
    r"\s*\.to\.(?:eql|equal)\(\s*(.+?)\s*\)"
)


class Assertion(BaseModel):
    """
    A translated Postman test-script assertion.

    kind selects the check; target and value carry its parameters:
      - response_time_below: value = threshold in milliseconds
      - header_present:      target = header name
      - json_field_equals:   target = top-level JSON field, value = expected
    """

    kind: Literal["response_time_below", "header_present", "json_field_equals"]
    target: str | None = None
    value: Any = None

    def to_pytest(self) -> str:
        """Render this assertion as a single pytest assert statement."""
        if self.kind == "response_time_below":
            return (
                f"assert response.elapsed.total_seconds() * 1000 < {self.value}, "
                f'"response time exceeded {self.value} ms"'
            )
        if self.kind == "header_present":
            return f'assert {self.target!r} in response.headers, "missing header {self.target}"'
        if self.kind == "json_field_equals":
            return (
                f"assert response.json().get({self.target!r}) == {self.value!r}, "
                f'"json field {self.target} mismatch"'
            )
        return ""


def _extract_assertions(events: list[dict[str, Any]]) -> list[Assertion]:
    """
    Translate recognised Postman test-script patterns into Assertions.

    Scans the 'test' event scripts for the supported idioms: response time,
    header presence, and JSON field equality. Status checks are excluded here
    because they are handled by expected_status. Unrecognised patterns are
    skipped so the generated test never carries a broken assert.
    """
    assertions: list[Assertion] = []
    for event in events:
        if event.get("listen") != "test":
            continue
        script = "\n".join(event.get("script", {}).get("exec", []))
        for match in _RESP_TIME_RE.finditer(script):
            assertions.append(Assertion(kind="response_time_below", value=int(match.group(1))))
        for match in _HEADER_RE.finditer(script):
            assertions.append(Assertion(kind="header_present", target=match.group(2)))
        for match in _JSON_FIELD_RE.finditer(script):
            value = _parse_js_value(match.group(2))
            if value is None:
                continue
            assertions.append(
                Assertion(kind="json_field_equals", target=match.group(1), value=value)
            )
    return assertions


class ParsedRequest(BaseModel):
    name: str
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    body_mode: str = "raw"  # raw | urlencoded | formdata
    form_fields: dict[str, str] | None = None  # set for urlencoded / formdata
    expected_status: int
    assertions: list[Assertion] = []  # translated from Postman test scripts
    folder: str | None
    final_test_name: str = ""  # filled by _disambiguate after parse

    @field_validator("method")
    @classmethod
    def normalise_method(cls, v: str) -> str:
        return v.upper()

    @field_validator("url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        return _replace_vars(v.strip())

    @property
    def test_name(self) -> str:
        """
        Slug suitable for use as a pytest function name.

        Returns the base name before disambiguation. Identical bases across
        multiple requests are resolved later via _disambiguate, which writes
        the final unique name into final_test_name.
        """
        if self.final_test_name:
            return self.final_test_name
        return self._base_test_name()

    def _base_test_name(self) -> str:
        name_slug = _slugify(self.name)
        if self.folder:
            return f"test_{self.folder}_{self.method.lower()}_{name_slug}"
        return f"test_{self.method.lower()}_{name_slug}"


def _parse_item(
    item: dict[str, Any], folder: str | None = None, _depth: int = 0
) -> list[ParsedRequest]:
    """Recursively parse a Postman item (request or folder)."""
    results: list[ParsedRequest] = []

    # A malformed collection can carry non-object items (scalars, lists). Skip
    # them with a warning rather than crashing the whole run.
    if not isinstance(item, dict):
        logger.warning("Skipping item that is not an object: %r", item)
        return results

    # Folder: recurse into sub-items
    if "item" in item:
        if _depth >= _MAX_FOLDER_DEPTH:
            logger.warning(
                "Skipping folder '%s': nesting exceeds %d levels.",
                item.get("name", "?"),
                _MAX_FOLDER_DEPTH,
            )
            return results
        sub_items = item["item"]
        if not isinstance(sub_items, list):
            logger.warning("Skipping folder '%s': 'item' is not a list.", item.get("name", "?"))
            return results
        folder_name = _slugify(item.get("name", ""))
        if folder_name == "unnamed":
            folder_name = ""
        for sub in sub_items:
            results.extend(_parse_item(sub, folder=folder_name or None, _depth=_depth + 1))
        return results

    # Request item
    request = item.get("request")
    if not request:
        return results

    try:
        method = request.get("method", "GET")
        url_obj = request.get("url", {})
        raw_url = url_obj.get("raw", "") if isinstance(url_obj, dict) else str(url_obj)

        headers: dict[str, str] = {
            h["key"]: _replace_vars(h.get("value", ""))
            for h in request.get("header", [])
            if h.get("key") and not h.get("disabled")
        }

        body: str | None = None
        body_mode = "raw"
        form_fields: dict[str, str] | None = None
        body_obj = request.get("body")
        if body_obj:
            mode = body_obj.get("mode")
            if mode == "raw":
                raw = body_obj.get("raw", "").strip()
                if raw:
                    body = raw
            elif mode in ("urlencoded", "formdata"):
                fields: dict[str, str] = {}
                for f in body_obj.get(mode, []):
                    if not f.get("key") or f.get("disabled"):
                        continue
                    # formdata file fields carry no inline value to render;
                    # render text fields only (file upload is a separate roadmap item).
                    if mode == "formdata" and f.get("type") == "file":
                        continue
                    fields[f["key"]] = _replace_vars(f.get("value", ""))
                if fields:
                    body_mode = mode
                    form_fields = fields

        events = item.get("event", [])
        expected_status = _extract_status(events) or 200

        results.append(
            ParsedRequest(
                name=item.get("name", "unnamed"),
                method=method,
                url=raw_url,
                headers=headers,
                body=body,
                body_mode=body_mode,
                form_fields=form_fields,
                expected_status=expected_status,
                assertions=_extract_assertions(events),
                folder=folder,
            )
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        # AttributeError covers a non-dict sub-structure (request / a header
        # element / body / a form field arriving as a string or None), where a
        # `.get(...)` call would otherwise raise and abort the whole parse.
        logger.warning("Skipping item '%s': %s", item.get("name", "?"), exc)

    return results


def _disambiguate(requests: list[ParsedRequest]) -> None:
    """
    Resolve test-name collisions by appending numeric suffixes.

    Postman collections can have requests without unique names (e.g. multiple
    POST requests in the same folder, or a folder name that transliterates to
    the same slug as a sibling). Without disambiguation, the generator emits
    duplicate function definitions and Python silently keeps only the last one,
    losing test coverage. This pass walks the parsed list, detects identical
    base test names, and appends _1 / _2 / _N to colliding entries so every
    request maps to a unique pytest function. Emits a warning per affected
    base name so the user knows disambiguation happened.
    """
    base_names = [req._base_test_name() for req in requests]
    counts: dict[str, int] = {}
    for name in base_names:
        counts[name] = counts.get(name, 0) + 1

    duplicates = {name: count for name, count in counts.items() if count > 1}
    if not duplicates:
        # No collisions: leave final_test_name empty so test_name falls back
        # to the base. This keeps generated names stable for the common case.
        return

    for name, count in duplicates.items():
        logger.warning(
            "Disambiguating %d colliding requests with base name '%s' by appending numeric suffix",
            count,
            name,
        )

    seen: dict[str, int] = {}
    for req, base in zip(requests, base_names, strict=True):
        if base not in duplicates:
            req.final_test_name = base
            continue
        seen[base] = seen.get(base, 0) + 1
        req.final_test_name = f"{base}_{seen[base]}"


def parse_collection(path: Path) -> list[ParsedRequest]:
    """
    Load and parse a Postman Collection v2.1 JSON file.
    Returns a flat list of ParsedRequest objects.
    Malformed items are skipped with a warning.
    """
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except RecursionError as exc:
        raise ValueError("Collection JSON is nested too deeply to parse.") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Collection root must be a JSON object, got {type(data).__name__}.")

    info = data.get("info")
    schema = info.get("schema", "") if isinstance(info, dict) else ""
    if "v2.1" not in schema and "v2.0" not in schema:
        logger.warning("Unexpected collection schema: %s. Proceeding anyway.", schema)

    items = data.get("item", [])
    if not isinstance(items, list):
        logger.warning(
            "Collection 'item' is not a list (got %s); treating as empty.", type(items).__name__
        )
        items = []
    results: list[ParsedRequest] = []
    for item in items:
        results.extend(_parse_item(item))

    _disambiguate(results)
    logger.info("Parsed %d requests from collection", len(results))
    return results
