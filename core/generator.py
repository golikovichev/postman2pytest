"""
Pytest file generator.
Takes a list of ParsedRequest objects and renders them via Jinja2.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.parser import ParsedRequest

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


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
