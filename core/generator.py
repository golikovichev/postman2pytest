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
# Used when the collection names no resolvable base URL of its own.
_BASE_URL_FALLBACK = "http://localhost:8080"
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


def _strip_base_url(url: str, fixture_mode: bool = False, strip_leading: bool = True) -> str:
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
    if strip_leading:
        url = _ENV_PREFIX_RE.sub("", url)
    url = _ENV_VAR_RE.sub(lambda m: _token_repr(m.group(1), fixture_mode), url)
    return url


def _render_url(
    url: str,
    env: PostmanEnvironment | None = None,
    strip_leading: bool = True,
    base_var: str | None = None,
) -> str:
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

    # The base variable is stripped before inlining, not after. It maps to
    # BASE_URL (see _base_url_choice), so resolving it here would turn a
    # relative URL into an absolute literal and take the address out of the
    # reader's control at run time.
    if strip_leading:
        url = _strip_base_var(url, env, base_var)
        strip_leading = False
    url = _inline_env_tokens(url, env)
    fixture_mode = env is not None
    if url.startswith(("http://", "https://")):
        if "ENV_" not in url:
            return json.dumps(url)
        # Absolute URL that still carries unresolved variables (e.g. an inlined
        # base_url followed by a path variable). Render as an f-string so the
        # remaining tokens are interpolated instead of leaking as raw text.
        return 'f"' + _interpolate(url, fixture_mode) + '"'
    # Relative URL. Strip the leading base-URL variable (it maps to BASE_URL),
    # then build the f-string body via _interpolate so literal segments are
    # escaped. _strip_base_url does the token substitution but NOT the literal
    # escaping, so a URL carrying a brace / quote / backslash (e.g. an inline
    # JSON query param ?filter={"x":1}) produced invalid Python. Reusing
    # _interpolate keeps URL and header rendering on the same escaping path.
    if strip_leading:
        url = _ENV_PREFIX_RE.sub("", url)
    if not url:
        return 'f"{BASE_URL}"'  # the whole URL was the base variable
    return 'f"{BASE_URL}/' + _interpolate(url, fixture_mode) + '"'


def _escape_fstring_literal(literal: str) -> str:
    """Escape a literal segment for embedding inside a Python f-string.

    f-strings interpret backslash, the outer-quote char, and brace pairs.
    A single-line f-string is also terminated by a raw newline or carriage
    return, so those are rewritten to their escape sequences too. Each must
    be rewritten so the parser reads the original characters back as data,
    not as syntax.
    """
    return (
        literal.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("{", "{{")
        .replace("}", "}}")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


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


# Auth headers are pulled out of each test and centralised in an auth_headers
# fixture. The exact set covers Authorization (Bearer/Basic) and proxy auth; the
# pattern catches the common API-key / token header names. Keeping these out of
# the exact set (e.g. Authentication, WWW-Authenticate) avoids false positives.
_AUTH_HEADER_EXACT = frozenset({"authorization", "proxy-authorization"})
_AUTH_HEADER_RE = re.compile(
    r"api[-_]?key|x-auth-token|x-access-token|x-amz-security-token", re.IGNORECASE
)
_BEARER_BASIC_RE = re.compile(r"^(Bearer|Basic)\s+(\S.*)$", re.IGNORECASE)


def _is_auth_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in _AUTH_HEADER_EXACT or bool(_AUTH_HEADER_RE.search(lowered))


def _auth_env_name(name: str) -> str:
    """Environment variable name for a hardcoded auth secret.

    Authorization maps to AUTH_TOKEN; any other auth header (API-key style)
    maps to an upper snake-case of its own name (X-Api-Key -> X_API_KEY).
    """
    if name.lower() == "authorization":
        return "AUTH_TOKEN"
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def _file_env_name(key: str) -> str:
    """Environment variable name for a formdata file field's local path.

    The upload path is never hardcoded (it would be the collection author's
    local path). It becomes an env placeholder, e.g. `document` -> DOCUMENT_FILE,
    `profile pic` -> PROFILE_PIC_FILE, defaulting to the source basename.

    An all-non-ASCII key collapses to `_FILE` (same shape as `_auth_env_name`),
    so two such keys would share one env override; the distinct basename
    defaults still differ, so the generated code stays correct.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper() + "_FILE"


def _render_files(file_fields: list[tuple[str, str]]) -> str:
    """Python expression for a requests `files=` argument.

    Each file field opens a path read from an env placeholder, defaulting to the
    source basename. Unique keys render an idiomatic dict; a repeated key falls
    back to a list of tuples so every upload survives (a dict would drop one).
    """
    import json

    keys = [k for k, _ in file_fields]
    unique = len(set(keys)) == len(keys)
    entries: list[str] = []
    for key, filename in file_fields:
        opener = (
            f'open(os.environ.get({json.dumps(_file_env_name(key))}, {json.dumps(filename)}), "rb")'
        )
        entries.append(
            f"{json.dumps(key)}: {opener}" if unique else f"({json.dumps(key)}, {opener})"
        )
    body = ", ".join(entries)
    return "{" + body + "}" if unique else "[" + body + "]"


def _render_auth_value(name: str, value: str, env: PostmanEnvironment | None) -> str:
    """Python expression for one auth header value in the auth_headers fixture.

    The secret never lands in the source. Postman ENV_xxx tokens become
    os.environ lookups (not inlined, not a bare fixture reference, so the
    fixture is self-contained). A hardcoded token is replaced with an env
    placeholder, and a Bearer/Basic scheme prefix is preserved.
    """
    if "ENV_" in value:
        return 'f"' + _interpolate(value, fixture_mode=False) + '"'
    env_name = _auth_env_name(name)
    match = _BEARER_BASIC_RE.match(value)
    if match:
        scheme = match.group(1).capitalize()
        return f"f\"{scheme} {{os.environ.get({env_name!r}, '')}}\""
    return f"os.environ.get({env_name!r}, '')"


def _split_auth_headers(
    req: ParsedRequest, env: PostmanEnvironment | None
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Partition a request's headers into (non_auth, auth_items).

    non_auth stays a name->value dict rendered inline as before; auth_items is
    a list of (name, expression) pairs for the shared fixture.
    """
    non_auth: dict[str, str] = {}
    auth_items: list[tuple[str, str]] = []
    for key, value in req.headers.items():
        if _is_auth_header(key):
            auth_items.append((key, _render_auth_value(key, value, env)))
        else:
            non_auth[key] = value
    return non_auth, auth_items


_LEADING_VAR_RE = re.compile(r"^ENV_(\w+)")
# A leading variable stands for the whole base address only when the path
# separator (or the end of the URL) comes straight after it. In `{{host}}:{{port}}`
# the host variable is half an address, and treating it as the base would leave
# the port stranded at the front of the path.
_BASE_VAR_RE = re.compile(r"^ENV_(\w+)(?=/|$)")


def _base_url_choice(
    requests: list[ParsedRequest], env: PostmanEnvironment | None, fallback: str
) -> tuple[str | None, str]:
    """Pick the variable that stands for BASE_URL, and the default to give it.

    Requests are written relative to BASE_URL, so a leading variable resolving
    to an absolute address is the collection's own idea of where the API lives,
    and makes a far better default than a guess. The first such request wins.

    Two things this deliberately does not do. It does not accept a leading
    variable whose value is not an absolute URL: a tenant slug at the front of
    a path is a path segment, and promoting it to BASE_URL would both drop the
    segment and leave the address unusable. And it names the winning variable
    rather than just its value, so a request leading with a *different* host
    keeps that host instead of being retargeted to this one.

    Returns (variable name or None, BASE_URL default).
    """
    if env is None:
        return None, fallback
    for req in requests:
        if req.url.startswith(("http://", "https://")) or not req.strip_leading_url_var:
            continue
        match = _BASE_VAR_RE.match(req.url)
        if not match:
            continue
        resolved = env.inline_value(match.group(1))
        if resolved and resolved.startswith(("http://", "https://")):
            return match.group(1), resolved.rstrip("/")
    return None, fallback


def _strip_base_var(url: str, env: PostmanEnvironment | None, base_var: str | None) -> str:
    """Remove the leading variable when it maps to BASE_URL rather than to text.

    That is the case for the variable chosen as BASE_URL, and for one that
    resolves to nothing at all (unknown, or secret), which is where an
    unresolved leading variable has always gone. Any other leading variable is
    left in place to be inlined as a literal path segment.

    _render_url and _collect_fixtures both go through here, or the two would
    disagree about which names still need a fixture.
    """
    match = _LEADING_VAR_RE.match(url)
    if not match:
        return url
    name = match.group(1)
    if base_var is not None and name == base_var and _BASE_VAR_RE.match(url):
        return _ENV_PREFIX_RE.sub("", url)
    if env is not None and env.inline_value(name) is not None:
        return url  # resolvable, but not the base address: keep it in the path
    return _ENV_PREFIX_RE.sub("", url)


def _collect_fixtures(
    req: ParsedRequest, env: PostmanEnvironment | None, base_var: str | None = None
) -> list[str]:
    """Variable names in this request that become named pytest fixtures.

    A fixture is needed for every {{var}} that survives inlining (secret or
    unknown). The leading URL variable is excluded: it maps to BASE_URL, not
    a fixture. Auth-header variables are excluded too: they live in the
    auth_headers fixture. Only meaningful when an environment was supplied.
    """
    if env is None:
        return []
    names: set[str] = set()

    def _add_safe(text: str) -> None:
        names.update(n for n in _ENV_VAR_RE.findall(text) if _is_safe_fixture_name(n))

    url = req.url
    if not url.startswith(("http://", "https://")) and req.strip_leading_url_var:
        url = _strip_base_var(url, env, base_var)  # base var -> BASE_URL, not a fixture
    url = _inline_env_tokens(url, env)  # same order as _render_url, or the two disagree
    _add_safe(url)  # remaining url vars (absolute or relative)

    for key, value in req.headers.items():
        if _is_auth_header(key):
            continue  # handled by the auth_headers fixture, not a per-var fixture
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
    env.filters["render_files"] = _render_files
    env.filters["docstring"] = _docstring_safe
    env.filters["strip_base_url"] = _strip_base_url
    base_var, base_url_default = _base_url_choice(requests, postman_env, _BASE_URL_FALLBACK)
    env.filters["render_url"] = lambda url, strip_leading=True: _render_url(
        url, postman_env, strip_leading, base_var
    )
    env.filters["render_header_value"] = lambda value: _render_header_value(value, postman_env)

    template = env.get_template("test_collection.jinja2")

    fixtures_per_request = [_collect_fixtures(req, postman_env, base_var) for req in requests]
    all_fixtures = sorted({name for fx in fixtures_per_request for name in fx})

    # Split auth headers out of each request. non_auth headers render inline as
    # before; auth headers are collected once (union, first value wins) into the
    # shared auth_headers fixture written to conftest.py.
    non_auth_per_request: list[dict[str, str]] = []
    has_auth_per_request: list[bool] = []
    auth_headers_map: dict[str, str] = {}
    seen_auth_lower: set[str] = set()  # HTTP header names are case-insensitive
    for req in requests:
        non_auth, auth_items = _split_auth_headers(req, postman_env)
        non_auth_per_request.append(non_auth)
        has_auth_per_request.append(bool(auth_items))
        for name, expr in auth_items:
            if name.lower() in seen_auth_lower:
                continue  # same header in another casing: keep the first entry
            seen_auth_lower.add(name.lower())
            auth_headers_map[name] = expr

    params_per_request = [
        ", ".join(fx + (["auth_headers"] if has_auth else []))
        for fx, has_auth in zip(fixtures_per_request, has_auth_per_request, strict=True)
    ]

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rendered = template.render(
        requests=requests,
        base_url_default=base_url_default,
        fixtures_per_request=fixtures_per_request,
        all_fixtures=all_fixtures,
        non_auth_per_request=non_auth_per_request,
        has_auth_per_request=has_auth_per_request,
        params_per_request=params_per_request,
        collection_name=collection_name,
        generated_at=generated_at,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    logger.info("Written %d tests to %s", len(requests), output_path)

    if auth_headers_map:
        conftest_template = env.get_template("conftest.jinja2")
        conftest_rendered = conftest_template.render(
            auth_items=sorted(auth_headers_map.items()),
            collection_name=collection_name,
            generated_at=generated_at,
        )
        conftest_path = output_path.parent / "conftest.py"
        conftest_path.write_text(conftest_rendered, encoding="utf-8")
        logger.info("Written auth_headers fixture to %s", conftest_path)


def _to_python_repr(value: object) -> str:
    """Jinja2 filter: render a Python value as a repr-safe string."""
    import json

    return json.dumps(value, ensure_ascii=False)


def _docstring_safe(value: object) -> str:
    """Escape a value for safe embedding inside a triple-quoted docstring.

    The generated tests carry the request URL and collection name in a
    triple-double-quoted (\"\"\") docstring. Both are untrusted collection
    text: a value ending in a double-quote, containing a \"\"\" run, or
    ending in a backslash would otherwise terminate (or escape past) the
    docstring delimiter and break the whole module. Escaping every backslash
    and double-quote neutralises that (a \"\"\" run becomes three escaped
    quotes that cannot close the delimiter) while keeping the text readable.
    Safety is coupled to the template using \"\"\": if it ever switches to
    ''', this would need to escape the single-quote instead.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
