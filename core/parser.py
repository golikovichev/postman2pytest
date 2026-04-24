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

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def _replace_vars(value: str) -> str:
    """Replace Postman {{variable}} with Python os.environ placeholder."""
    return _VAR_RE.sub(r"ENV_\1", value)


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
        """Slug suitable for use as a pytest function name."""
        base = f"{self.method.lower()}_{self.name}"
        if self.folder:
            base = f"{self.folder}_{base}"
        slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
        return f"test_{slug}"


def _parse_item(item: dict, folder: str | None = None) -> list[ParsedRequest]:
    """Recursively parse a Postman item (request or folder)."""
    results: list[ParsedRequest] = []

    # Folder — recurse into sub-items
    if "item" in item:
        folder_name = re.sub(r"[^a-z0-9]+", "_", item.get("name", "").lower()).strip("_")
        for sub in item["item"]:
            results.extend(_parse_item(sub, folder=folder_name))
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

        results.append(ParsedRequest(
            name=item.get("name", "unnamed"),
            method=method,
            url=raw_url,
            headers=headers,
            body=body,
            expected_status=expected_status,
            folder=folder,
        ))
    except Exception as exc:
        logger.warning("Skipping item '%s': %s", item.get("name", "?"), exc)

    return results


def parse_collection(path: Path) -> list[ParsedRequest]:
    """
    Load and parse a Postman Collection v2.1 JSON file.
    Returns a flat list of ParsedRequest objects.
    Malformed items are skipped with a warning.
    """
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    schema = data.get("info", {}).get("schema", "")
    if "v2.1" not in schema and "v2.0" not in schema:
        logger.warning("Unexpected collection schema: %s — proceeding anyway", schema)

    items = data.get("item", [])
    results: list[ParsedRequest] = []
    for item in items:
        results.extend(_parse_item(item))

    logger.info("Parsed %d requests from collection", len(results))
    return results
