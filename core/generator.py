"""
Pytest file generator.
Takes a list of ParsedRequest objects and renders them via Jinja2.
"""

from __future__ import annotations

import keyword
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.environment import Environment as PostmanEnvironment
from core.parser import ParsedRequest

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_ENV_PREFIX_RE = re.compile(r"^ENV_\w+/?")
_ENV_VAR_RE = re.compile(r"ENV_(\w+)")

# A surviving variable becomes a pytest fixture only when its name is a usable,
# non-colliding Python identifier. Digit-leading names ({{2fa}}), keywords, and
# names that would shadow the generated module's own bindings fall back to an
# os.environ lookup so the generated file always compiles and runs correctly.
_RESERVED_FIXTURE_NAMES = frozenset(
    {"url", "headers", "data", "body", "response", "requests", "os", "pytest", "json", "BASE_URL"}
)


def _is_safe_fixture_name(name: str) -> bool:
    return (
        name.isidentifier() and not keyword.iskeyword(name) and name not in _RESERVED_FIXTURE_NAMES
    )


def _token_repr(name: str, fixture_mode: bool) -> str:
    """Inline expression for one ENV_xxx token: a bare fixture reference when in
    fixture_mode and the name is safe, otherwise an os.environ lookup."""
    if fixture_mode and _is_safe_fixture_name(name):
        return "{" + name + "}"
    return "{os.environ.get('" + name + "', '')}"


def _inline_env_tokens(value: str, env: PostmanEnvironment | None) -> str:
    """Replace ENV_xxx tokens that resolve to an inlinable (non-secret, known)
    value with the literal value. Secret and unknown variables are left as
    ENV_xxx tokens so they fall through to os.environ / a fixture downstream."""
    if env is None or "ENV_" not in value:
        return value

    def repl(match: re.Match[str]) -> str:
        resolved = env.inline_value(match.group(1))
        return resolved if resolved is not None else match.group(0)

    return _ENV_VAR_RE.sub(repl, value)


def _strip_base_url(url: str, fixture_mode: bool = False) -> str:
    """
    Transform ENV_xxx URLs for use in f-strings inside generated tests.

    ENV_base_url/api/v1/users  ->  api/v1/users
    path/ENV_version/users     ->  path/{os.environ.get('version', '')}/users

    With fixture_mode (an environment was supplied via --env), remaining
    ENV_xxx tokens become bare fixture references instead::

        path/ENV_version/users  ->  path/{version}/users

    Absolute URLs (http:// or https://) are returned as-is. Note: this filter
    is no longer the only entry point. See _render_url, which routes absolute
    URLs around BASE_URL prepending entirely.
    """
    if url.startswith(("http://", "https://")):
        return url
    url = _ENV_PREFIX_RE.sub("", url)
    url = _ENV_VAR_RE.sub(lambda m: _token_repr(m.group(1), fixture_mode), url)
    return url


def _render_url(url: str, env: PostmanEnvironment | None = None) -> str:
    """Render a URL as a Python expression for the generated test code.

    When an environment is provided, non-secret known variables are inlined
    as literal values first; secret/unknown variables stay as os.environ
    lookups.

    Absolute URL (http:// or https://) -> JSON string literal, no BASE_URL
    (or an f-string when it still carries unresolved variables).
    Relative URL -> f-string with `{BASE_URL}/` prefix. Remaining ENV_xxx
    tokens become bare fixture references ({name}) under --env, or
    os.environ.get('xxx', '') lookups otherwise.

    Closes the bug where absolute URLs (Postman collections that mix
    internal endpoints with third-party API calls) were emitted as
    f"{BASE_URL}/https://...", producing a broken request URL at runtime.
    """
    import json

    url = _inline_env_tokens(url, env)
    fixture_mode = env is not None
    if url.startswith(("http://", "https://")):
        if "ENV_" not in url:
            return json.dumps(url)
        # Absolute URL that still carries unresolved variables (e.g. an inlined
        # base_url followed by a path variable). Render as an f-string so the
        # remaining tokens are interpolated instead of leaking as raw text.
        return 'f"' + _interpolate(url, fixture_mode) + '"'
    stripped = _strip_base_url(url, fixture_mode=fixture_mode)
    return 'f"{BASE_URL}/' + stripped + '"'


def _escape_fstring_literal(literal: str) -> str:
    """Escape a literal segment for embedding inside a Python f-string.

    f-strings interpret backslash, the outer-quote char, and brace pairs.
    Each must be rewritten so the parser reads the original characters
    back as data, not as syntax.
    """
    return literal.replace("\\", "\\\\").replace('"', '\\"').replace("{", "{{").replace("}", "}}")


def _interpolate(value: str, fixture_mode: bool) -> str:
    """Build the body of an f-string from a value containing ENV_xxx tokens.

    Literal spans are escaped; each ENV_xxx token becomes a bare fixture
    reference ({name}) in fixture_mode, or an os.environ.get lookup otherwise.
    """
    parts: list[str] = []
    cursor = 0
    for match in _ENV_VAR_RE.finditer(value):
        parts.append(_escape_fstring_literal(value[cursor : match.start()]))
        parts.append(_token_repr(match.group(1), fixture_mode))
        cursor = match.end()
    parts.append(_escape_fstring_literal(value[cursor:]))
    return "".join(parts)


def _render_header_value(value: str, env: PostmanEnvironment | None = None) -> str:
    """Render a header value as a Python expression.

    Plain values become a JSON string literal: "application/json".
    Values with ENV_xxx become a Python f-string: f"Bearer {os.environ.get('token', '')}"

    When an environment is provided, non-secret known variables are inlined as
    literal values first; secret/unknown variables stay as os.environ lookups
    (or fixture references), so a secret token never lands in the generated
    source.
    """
    import json

    value = _inline_env_tokens(value, env)
    if "ENV_" not in value:
        return json.dumps(value)
    return 'f"' + _interpolate(value, fixture_mode=env is not None) + '"'


def _collect_fixtures(req: ParsedRequest, env: PostmanEnvironment | None) -> list[str]:
    """Variable names in this request that become named pytest fixtures.

    A fixture is needed for every {{var}} that survives inlining (secret or
    unknown). The leading URL variable is excluded: it maps to BASE_URL, not
    a fixture. Only meaningful when an environment was supplied.
    """
    if env is None:
        return []
    names: set[str] = set()

    def _add_safe(text: str) -> None:
        names.update(n for n in _ENV_VAR_RE.findall(text) if _is_safe_fixture_name(n))

    url = _inline_env_tokens(req.url, env)
    if not url.startswith(("http://", "https://")):
        url = _ENV_PREFIX_RE.sub("", url)  # relative: leading var -> BASE_URL, not a fixture
    _add_safe(url)  # remaining url vars (absolute or relative)

    for value in req.headers.values():
        _add_safe(_inline_env_tokens(value, env))

    return sorted(names)


def generate(
    requests: list[ParsedRequest],
    collection_name: str,
    output_path: Path,
    postman_env: PostmanEnvironment | None = None,
) -> None:
    """
    Render parsed requests into a pytest file at output_path.
    Creates parent directories if needed.

    When postman_env is provided (from --env), non-secret variables are
    resolved to literal values; secret/unknown variables stay as os.environ
    lookups.
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
    env.filters["render_url"] = lambda url: _render_url(url, postman_env)
    env.filters["render_header_value"] = lambda value: _render_header_value(value, postman_env)

    template = env.get_template("test_collection.jinja2")

    fixtures_per_request = [_collect_fixtures(req, postman_env) for req in requests]
    all_fixtures = sorted({name for fx in fixtures_per_request for name in fx})

    rendered = template.render(
        requests=requests,
        fixtures_per_request=fixtures_per_request,
        all_fixtures=all_fixtures,
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
