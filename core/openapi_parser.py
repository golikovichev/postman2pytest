"""
OpenAPI 3.x parser.

Parses an OpenAPI 3.x specification (JSON or YAML) into the same list of
ParsedRequest objects the Postman parser emits, so the existing generator and
templates render an identical-shape pytest suite from either input format.

Path parameters ({id}) and query/header parameters are mapped to the same
ENV_xxx placeholder mechanism the Postman path uses: a path segment {id}
becomes {{id}} which ParsedRequest normalises to ENV_id, and the generator then
renders it as an os.environ lookup (or a fixture under --env). This keeps a
single downstream code path for both input formats.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.parser import ParsedRequest, _disambiguate, _replace_vars, _slugify

logger = logging.getLogger(__name__)

# HTTP methods an OpenAPI Path Item Object may declare (OpenAPI 3.x fixed fields).
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# A path-template placeholder: the {name} spans in an OpenAPI path (e.g. /users/{id}).
_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def _sanitize_var(name: str) -> str:
    """Reduce a parameter name to the \\w+ token ParsedRequest recognises.

    ParsedRequest replaces {{name}} with ENV_name only when name matches \\w+,
    so a header/path/query parameter like 'X-Request-Id' must collapse to
    'X_Request_Id' before it is wrapped as a placeholder.
    """
    cleaned = re.sub(r"\W+", "_", name).strip("_")
    return cleaned or "param"


def _load_spec(path: Path) -> Any:
    """Load an OpenAPI spec from JSON or YAML.

    YAML is chosen by extension (.yaml/.yml); otherwise JSON is tried first and
    YAML is used as a fallback (a .json extension is trusted, but an unknown
    extension still parses a YAML document, which is a superset of JSON).
    """
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import yaml

        return yaml.safe_load(text)


def _placeholder_for_schema(schema: dict[str, Any]) -> Any:
    """A concrete sample value for a property schema.

    Prefers an explicit example/default, then an enum's first option, then a
    type-appropriate empty value. Used to synthesise a JSON request body when
    the spec carries no example of its own.
    """
    if not isinstance(schema, dict):
        return ""
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    kind = schema.get("type", "")
    return {
        "integer": 0,
        "number": 0,
        "boolean": False,
        "array": [],
        "object": {},
        "string": "",
    }.get(kind, "")


def _example_body(operation: dict[str, Any]) -> str | None:
    """Build a raw JSON body string from an operation's JSON requestBody.

    Uses a media-type example, then a schema example, then a skeleton built
    from the schema properties. Returns None when there is no JSON body to send.
    """
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None

    if "example" in media:
        return json.dumps(media["example"])

    schema = media.get("schema")
    if isinstance(schema, dict):
        if "example" in schema:
            return json.dumps(schema["example"])
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            skeleton = {name: _placeholder_for_schema(prop) for name, prop in properties.items()}
            return json.dumps(skeleton)
    return None


def _merge_parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine path-item-level and operation-level parameters.

    An operation-level parameter overrides a path-item one that shares the same
    (name, in) pair, per the OpenAPI specification.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        if not isinstance(source, list):
            continue
        for param in source:
            if not isinstance(param, dict) or "name" not in param:
                continue
            merged[(param["name"], param.get("in", ""))] = param
    return list(merged.values())


def _expected_status(operation: dict[str, Any]) -> int:
    """Pick the lowest 2xx response code, defaulting to 200.

    Mirrors the Postman path, whose expected_status also defaults to 200 when a
    collection carries no explicit status assertion.
    """
    responses = operation.get("responses")
    if isinstance(responses, dict):
        codes = [
            int(code)
            for code in responses
            if isinstance(code, str) and code.isdigit() and 200 <= int(code) < 300
        ]
        if codes:
            return min(codes)
    return 200


def _build_url(path: str, params: list[dict[str, Any]]) -> str:
    """Assemble a relative URL with {{var}} placeholders for path/query params.

    Path template segments {id} become {{id}}; query parameters are appended as
    key={{key}} pairs. The leading slash is dropped so the generator's relative
    URL path (f"{BASE_URL}/...") does not produce a double slash.
    """
    templated = _PATH_PARAM_RE.sub(lambda m: "{{" + _sanitize_var(m.group(1)) + "}}", path)
    templated = templated.lstrip("/")

    query = [p for p in params if p.get("in") == "query"]
    if query:
        pairs = [f"{p['name']}={{{{{_sanitize_var(p['name'])}}}}}" for p in query]
        templated = f"{templated}?{'&'.join(pairs)}"
    return templated


def _operation_name(method: str, path: str, operation: dict[str, Any]) -> str:
    """Human-ish request name: operationId, then summary, then 'METHOD path'."""
    for key in ("operationId", "summary"):
        value = operation.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{method.upper()} {path}"


def spec_title(path: Path) -> str | None:
    """Return the spec's info.title, or None when it cannot be read.

    Used by the CLI to name the generated suite, mirroring how the Postman path
    reads info.name.
    """
    try:
        data = _load_spec(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        info = data.get("info")
        if isinstance(info, dict):
            title = info.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
    return None


def parse_openapi(path: Path) -> list[ParsedRequest]:
    """Parse an OpenAPI 3.x spec (JSON or YAML) into a list of ParsedRequest.

    Each operation under paths becomes one ParsedRequest whose shape matches the
    Postman parser's output, so the generator renders both formats identically.
    """
    data = _load_spec(path)
    if not isinstance(data, dict):
        raise ValueError(f"OpenAPI spec root must be a mapping, got {type(data).__name__}.")

    version = data.get("openapi", "")
    if not (isinstance(version, str) and version.startswith("3.")):
        logger.warning("Unexpected or missing openapi version: %r. Proceeding anyway.", version)

    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        logger.warning(
            "'paths' is not a mapping (got %s); treating as empty.", type(paths).__name__
        )
        paths = {}

    results: list[ParsedRequest] = []
    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            logger.warning("Skipping path '%s': item is not a mapping.", path_str)
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            try:
                params = _merge_parameters(path_item, operation)
                # ParsedRequest has no header validator (unlike url), so resolve
                # the {{name}} placeholder to an ENV_ token here, exactly as the
                # Postman parser does for its own header values.
                headers = {
                    p["name"]: _replace_vars("{{" + _sanitize_var(p["name"]) + "}}")
                    for p in params
                    if p.get("in") == "header"
                }
                tags = operation.get("tags")
                folder = None
                if isinstance(tags, list) and tags and isinstance(tags[0], str):
                    slug = _slugify(tags[0])
                    folder = slug if slug != "unnamed" else None

                results.append(
                    ParsedRequest(
                        name=_operation_name(method, path_str, operation),
                        method=method,
                        url=_build_url(path_str, params),
                        headers=headers,
                        body=_example_body(operation),
                        expected_status=_expected_status(operation),
                        folder=folder,
                        # OpenAPI URLs are base-URL-relative with no leading
                        # base-URL variable, so a leading path parameter must
                        # survive generation (see ParsedRequest field docs).
                        strip_leading_url_var=False,
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                logger.warning("Skipping %s %s: %s", method.upper(), path_str, exc)

    _disambiguate(results)
    logger.info("Parsed %d requests from OpenAPI spec", len(results))
    return results
