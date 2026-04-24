"""
Pytest file generator.
Takes a list of ParsedRequest objects and renders them via Jinja2.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.parser import ParsedRequest

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_ENV_PREFIX_RE = re.compile(r"^ENV_\w+/?")
_ENV_VAR_RE = re.compile(r"ENV_(\w+)")


def _strip_base_url(url: str) -> str:
    """
    Transform ENV_xxx URLs for use in f-strings inside generated tests.

    ENV_base_url/api/v1/users  →  api/v1/users
    path/ENV_version/users     →  path/{os.environ.get('version', '')}/users
    """
    url = _ENV_PREFIX_RE.sub("", url)
    url = _ENV_VAR_RE.sub(r"{os.environ.get('\1', '')}", url)
    return url


def _render_header_value(value: str) -> str:
    """
    Render a header value as a Python expression.

    Plain values → JSON string literal: "application/json"
    Values with ENV_xxx → f-string: f"Bearer {os.environ.get('token', '')}"
    """
    import json
    if "ENV_" not in value:
        return json.dumps(value)
    fstring_body = _ENV_VAR_RE.sub(r"{os.environ.get('\1', '')}", value)
    # Escape any existing backslashes/quotes in the non-ENV portions
    return f'f"{fstring_body}"'


def generate(
    requests: list[ParsedRequest],
    collection_name: str,
    output_path: Path,
) -> None:
    """
    Render parsed requests into a pytest file at output_path.
    Creates parent directories if needed.
    """
    if not requests:
        logger.warning("No requests to generate — output file not written")
        return

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"] = _to_python_repr
    env.filters["strip_base_url"] = _strip_base_url
    env.filters["render_header_value"] = _render_header_value

    template = env.get_template("test_collection.jinja2")

    rendered = template.render(
        requests=requests,
        collection_name=collection_name,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    logger.info("Written %d tests to %s", len(requests), output_path)


def _to_python_repr(value: object) -> str:
    """Jinja2 filter: render a Python value as a repr-safe string."""
    import json
    return json.dumps(value, ensure_ascii=False)
