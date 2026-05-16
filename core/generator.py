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

    ENV_base_url/api/v1/users  ->  api/v1/users
    path/ENV_version/users     ->  path/{os.environ.get('version', '')}/users

    Absolute URLs (http:// or https://) are returned as-is. The generated
    test code is expected to detect that and skip BASE_URL prepending.
    """
    if url.startswith(("http://", "https://")):
        return url
    url = _ENV_PREFIX_RE.sub("", url)
    url = _ENV_VAR_RE.sub(r"{os.environ.get('\1', '')}", url)
    return url


def _escape_fstring_literal(literal: str) -> str:
    """Escape a literal segment for embedding inside a Python f-string.

    f-strings interpret backslash, the outer-quote char, and brace pairs.
    Each must be rewritten so the parser reads the original characters
    back as data, not as syntax.
    """
    return literal.replace("\\", "\\\\").replace('"', '\\"').replace("{", "{{").replace("}", "}}")


def _render_header_value(value: str) -> str:
    """Render a header value as a Python expression.

    Plain values become a JSON string literal: "application/json".
    Values with ENV_xxx become a Python f-string: f"Bearer {os.environ.get('token', '')}"

    Literal portions of the value (everything outside the ENV_xxx tokens)
    must be escaped before they land inside the f-string. Without this
    pass, a captured header containing a double quote or a curly brace
    produces either a broken f-string or, worse, valid Python with extra
    statements injected after the closing quote.
    """
    import json

    if "ENV_" not in value:
        return json.dumps(value)

    parts: list[str] = []
    cursor = 0
    for match in _ENV_VAR_RE.finditer(value):
        parts.append(_escape_fstring_literal(value[cursor : match.start()]))
        parts.append(f"{{os.environ.get('{match.group(1)}', '')}}")
        cursor = match.end()
    parts.append(_escape_fstring_literal(value[cursor:]))
    return 'f"' + "".join(parts) + '"'


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
        logger.warning("No requests to generate. Output file not written.")
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
