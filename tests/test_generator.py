"""Tests for core/generator.py"""

import pytest

from core.generator import _render_url, _strip_base_url, generate
from core.parser import ParsedRequest

# Fixtures


def _req(**overrides) -> ParsedRequest:
    defaults = dict(
        name="Get users",
        method="GET",
        url="ENV_base_url/api/v1/users",
        headers={},
        body=None,
        expected_status=200,
        folder=None,
    )
    defaults.update(overrides)
    return ParsedRequest(**defaults)


# Generate: basic output


def test_generate_creates_file(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req()], collection_name="My API", output_path=out)
    assert out.exists()


def test_generate_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "dir" / "test_api.py"
    generate([_req()], collection_name="My API", output_path=out)
    assert out.exists()


def test_generate_empty_list_skips_write(tmp_path):
    out = tmp_path / "test_api.py"
    generate([], collection_name="Empty", output_path=out)
    assert not out.exists()


def test_generate_contains_collection_name(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req()], collection_name="Payments API", output_path=out)
    assert "Payments API" in out.read_text(encoding="utf-8")


def test_generate_contains_base_url_env(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req()], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert 'os.environ.get("BASE_URL"' in content


# Test function names


def test_generate_test_function_name(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(name="List all items", method="GET", folder=None)
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "def test_get_list_all_items()" in content


def test_generate_folder_in_function_name(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(name="Create", method="POST", folder="users")
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "def test_users_post_create()" in content


# Http methods


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
def test_generate_correct_http_method(tmp_path, method):
    out = tmp_path / "test_api.py"
    req = _req(method=method)
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert f"requests.{method.lower()}(" in content


# Body handling


def test_generate_no_body_omits_json_arg(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req(body=None)], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "json=body" not in content


def test_generate_body_included_as_json(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(method="POST", body='{"name": "Alice"}')
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "json=body" in content
    assert "Alice" in content  # body content present (JSON-encoded in source)


# Status assertion


def test_generate_status_assertion_200(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req(expected_status=200)], collection_name="API", output_path=out)
    assert "== 200" in out.read_text(encoding="utf-8")


def test_generate_status_assertion_201(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req(expected_status=201)], collection_name="API", output_path=out)
    assert "== 201" in out.read_text(encoding="utf-8")


# Headers


def test_generate_headers_present(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(headers={"Authorization": "Bearer token", "Accept": "application/json"})
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    conftest = (out.parent / "conftest.py").read_text(encoding="utf-8")
    # non-auth header stays inline; the auth header moves to the shared fixture.
    assert "Accept" in content
    assert "**auth_headers" in content
    assert "Bearer token" not in content
    assert "Authorization" in conftest
    assert "AUTH_TOKEN" in conftest
    assert "Bearer token" not in conftest


def test_generate_empty_headers_is_empty_dict(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req(headers={})], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "{}" in content


def test_generate_env_var_in_header_value(tmp_path):
    """ENV_token in an auth header becomes os.environ.get('token', '') in the fixture."""
    out = tmp_path / "test_api.py"
    req = _req(headers={"Authorization": "Bearer ENV_token"})
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    conftest = (out.parent / "conftest.py").read_text(encoding="utf-8")
    # Authorization is centralised in the auth_headers fixture (conftest).
    assert "os.environ.get('token'" in conftest
    assert "ENV_token" not in content  # must not be literal
    assert "ENV_token" not in conftest


# Multiple requests


def test_generate_multiple_requests(tmp_path):
    out = tmp_path / "test_api.py"
    reqs = [
        _req(name="List", method="GET"),
        _req(name="Create", method="POST", body='{"x": 1}', expected_status=201),
        _req(name="Delete", method="DELETE", expected_status=204),
    ]
    generate(reqs, collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert content.count("def test_") == 3
    assert "== 201" in content
    assert "== 204" in content


# Valid python syntax


def test_generate_output_is_valid_python(tmp_path):
    out = tmp_path / "test_api.py"
    reqs = [
        _req(name="List", method="GET", headers={"X-Key": "val"}),
        _req(name="Create", method="POST", body='{"a": 1}', expected_status=201),
    ]
    generate(reqs, collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    # compile() raises SyntaxError on invalid Python
    compile(code, str(out), "exec")


# Adversarial header values (H1 fix - generated f-strings must escape
# literal portions so a captured header cannot inject Python code).


def test_header_value_with_double_quote_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(
        headers={
            "X-Evil": 'pre"; import os; os.system("evil"); ENV_token "post',
        }
    )
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")
    # The literal portion of the header value must not produce an
    # importable os.system call site at module level.
    import ast

    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            target = (
                f"{fn.value.id}.{fn.attr}"
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                else None
            )
            assert target != "os.system", "Header value injection executed"


def test_header_value_with_braces_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(headers={"X-Brace": "literal {0} braces with ENV_token suffix"})
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_header_value_with_backslash_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(headers={"X-Slash": "path\\to\\thing ENV_token end"})
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_header_value_plain_json_string_path_unchanged(tmp_path):
    """Plain (no ENV_) values should still go through json.dumps and
    land as a normal Python string literal."""
    out = tmp_path / "test_api.py"
    req = _req(headers={"Content-Type": "application/json"})
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    assert '"application/json"' in code
    compile(code, str(out), "exec")


# Coverage gap closer (added 2026-05-19)


def test_absolute_https_url_passthrough(tmp_path):
    """Absolute http/https URL must be returned as-is by _normalise_url.

    Covers generator.py L35: `if url.startswith(("http://", "https://")): return url`.
    The generated test code is expected to detect absolute and skip BASE_URL prepend.
    """
    out = tmp_path / "test_api.py"
    req = _req(url="https://api.example.com/health")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    # URL appears verbatim
    assert "https://api.example.com/health" in code
    # Negative assertions: no BASE_URL concatenation in front of the absolute URL
    assert 'BASE_URL + "https://api.example.com' not in code
    assert 'f"{BASE_URL}https://api.example.com' not in code
    assert 'f"{BASE_URL}/https://api.example.com' not in code
    compile(code, str(out), "exec")


def test_absolute_http_url_passthrough(tmp_path):
    """Same as above but for http:// scheme."""
    out = tmp_path / "test_api.py"
    req = _req(url="http://internal-svc/api/v1/ping")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    assert "http://internal-svc/api/v1/ping" in code
    assert 'BASE_URL + "http://internal-svc' not in code
    assert 'f"{BASE_URL}http://internal-svc' not in code
    compile(code, str(out), "exec")


# Direct unit tests for the URL filters (added 2026-05-19)
# `_render_url` is the primary template entry point; `_strip_base_url`
# remains exported as a Jinja filter for backward compatibility и
# is reached directly only by external callers / custom templates.


def test_strip_base_url_returns_absolute_url_as_is():
    """`_strip_base_url` was designed to passthrough absolute URLs.

    The bug surfaced 19.05: the template did not honour the passthrough
    and prepended {BASE_URL}/ anyway. `_render_url` now routes around
    that. Direct callers (custom Jinja templates) still see passthrough.
    """
    assert _strip_base_url("https://api.example.com/x") == "https://api.example.com/x"
    assert _strip_base_url("http://internal/y") == "http://internal/y"


def test_strip_base_url_strips_env_prefix():
    """Relative URL with ENV_base_url prefix is stripped clean."""
    assert _strip_base_url("ENV_base_url/api/v1/users") == "api/v1/users"


def test_strip_base_url_interpolates_inner_env_var():
    """Mid-path ENV_xxx becomes os.environ.get('xxx', '')."""
    out = _strip_base_url("path/ENV_version/users")
    assert out == "path/{os.environ.get('version', '')}/users"


def test_render_url_absolute_emits_json_literal():
    """Absolute URL goes through json.dumps so it is a plain Python string."""
    assert _render_url("https://api.example.com/x") == '"https://api.example.com/x"'


def test_render_url_relative_emits_base_url_fstring():
    """Relative URL builds an f-string with the BASE_URL prefix."""
    assert _render_url("ENV_base_url/api/v1/users") == 'f"{BASE_URL}/api/v1/users"'


# Adversarial URL values. The header path escapes f-string metacharacters
# (see test_header_value_with_* above), but the relative-URL path was built
# from _strip_base_url, which did NOT escape literals. A URL carrying a
# double quote, a backslash, or a literal brace therefore produced invalid
# Python (unterminated f-string / stray replacement field). Common real
# trigger: an inline-JSON query param like ?filter={"status":"active"}.


def test_url_with_double_quote_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url='ENV_base_url/search?q="hello"')
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")  # was SyntaxError: unterminated f-string


def test_url_with_inline_json_query_param_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url='ENV_base_url/search?filter={"status":"active"}')
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_url_with_braces_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url="ENV_base_url/items/{item_id}/detail")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_url_with_backslash_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url="ENV_base_url/path\\to\\thing")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_url_with_newline_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url="ENV_base_url/foo\nbar")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")  # was SyntaxError: unterminated f-string


def test_url_with_carriage_return_is_safe(tmp_path):
    out = tmp_path / "test_api.py"
    req = _req(url="ENV_base_url/foo\rbar")
    generate([req], collection_name="API", output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")


def test_render_url_relative_newline_preserved_at_runtime():
    """A newline in a relative URL survives as data, not as a source-line break."""
    expr = _render_url("ENV_base_url/foo\nbar")
    rendered = eval(expr, {"BASE_URL": "https://api.example.com"})  # noqa: S307
    assert rendered == "https://api.example.com/foo\nbar"


def test_render_url_relative_literal_brace_preserved_at_runtime():
    """A literal brace in a relative URL must survive as data, not become an
    f-string replacement field. It is doubled so the f-string renders it back."""
    expr = _render_url("ENV_base_url/items/{item_id}/detail")
    rendered = eval(expr, {"BASE_URL": "https://api.example.com"})  # noqa: S307
    assert rendered == "https://api.example.com/items/{item_id}/detail"


def test_render_url_relative_json_query_param_valid_and_correct():
    expr = _render_url('ENV_base_url/search?filter={"status":"active"}')
    rendered = eval(expr, {"BASE_URL": "https://api.example.com"})  # noqa: S307
    assert rendered == 'https://api.example.com/search?filter={"status":"active"}'


def test_collection_name_with_quotes_docstring_is_safe(tmp_path):
    """Collection name and URL land in triple-quoted docstrings. Untrusted
    text with a trailing quote or a ''' run must not terminate the docstring
    and break the module."""
    out = tmp_path / "test_api.py"
    req = _req(url='ENV_base_url/x?q="v"')
    generate([req], collection_name='My """API""" \\ end"', output_path=out)
    code = out.read_text(encoding="utf-8")
    compile(code, str(out), "exec")
