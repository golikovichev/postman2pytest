"""Tests for core/generator.py"""

import pytest

from core.generator import generate
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
    assert "Authorization" in content
    assert "Bearer token" in content


def test_generate_empty_headers_is_empty_dict(tmp_path):
    out = tmp_path / "test_api.py"
    generate([_req(headers={})], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "{}" in content


def test_generate_env_var_in_header_value(tmp_path):
    """ENV_token in header value should become os.environ.get('token', '') f-string."""
    out = tmp_path / "test_api.py"
    req = _req(headers={"Authorization": "Bearer ENV_token"})
    generate([req], collection_name="API", output_path=out)
    content = out.read_text(encoding="utf-8")
    assert "os.environ.get('token'" in content
    assert "ENV_token" not in content  # must not be literal


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
