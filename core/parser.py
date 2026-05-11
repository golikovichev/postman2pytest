"""
Postman Collection v2.1 parser.
Validates and flattens collection items into a list of ParsedRequest objects.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator
from unidecode import unidecode

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


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


def _extract_status(events: list[dict]) -> int | None:
    """
    Try to extract expected status code from Postman test scripts.
    Looks for: pm.response.to.have.status(201)
    """
    pattern = re.compile(r"\.have\.status\((\d+)\)")
    for event in events:
        if event.get("listen") != "test":
            continue
        script = "\n".join(event.get("script", {}).get("exec", []))
        match = pattern.search(script)
        if match:
            return int(match.group(1))
    return None


class ParsedRequest(BaseModel):
    name: str
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    expected_status: int
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


def _parse_item(item: dict, folder: str | None = None) -> list[ParsedRequest]:
    """Recursively parse a Postman item (request or folder)."""
    results: list[ParsedRequest] = []

    # Folder: recurse into sub-items
    if "item" in item:
        folder_name = _slugify(item.get("name", ""))
        if folder_name == "unnamed":
            folder_name = ""
        for sub in item["item"]:
            results.extend(_parse_item(sub, folder=folder_name or None))
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
        body_obj = request.get("body")
        if body_obj and body_obj.get("mode") == "raw":
            raw = body_obj.get("raw", "").strip()
            if raw:
                body = raw

        events = item.get("event", [])
        expected_status = _extract_status(events) or 200

        results.append(
            ParsedRequest(
                name=item.get("name", "unnamed"),
                method=method,
                url=raw_url,
                headers=headers,
                body=body,
                expected_status=expected_status,
                folder=folder,
            )
        )
    except Exception as exc:
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
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    schema = data.get("info", {}).get("schema", "")
    if "v2.1" not in schema and "v2.0" not in schema:
        logger.warning("Unexpected collection schema: %s. Proceeding anyway.", schema)

    items = data.get("item", [])
    results: list[ParsedRequest] = []
    for item in items:
        results.extend(_parse_item(item))

    _disambiguate(results)
    logger.info("Parsed %d requests from collection", len(results))
    return results
