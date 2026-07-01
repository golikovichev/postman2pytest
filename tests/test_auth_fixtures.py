"""Tests for auth-header extraction into a shared conftest fixture (issue #2).

Auth headers (Authorization Bearer/Basic, API key headers) are pulled out of
each generated test and centralised in an `auth_headers` fixture written to a
generated `conftest.py`. The test functions take the fixture and merge it into
their headers, and the secret value is replaced with an environment-variable
placeholder so no token lands in the generated source.
"""

import ast

from core.generator import generate
from core.parser import ParsedRequest


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


def _gen(reqs, tmp_path, name="test_api.py"):
    out = tmp_path / name
    generate(reqs, collection_name="API", output_path=out)
    module = out.read_text(encoding="utf-8")
    conftest_path = tmp_path / "conftest.py"
    conftest = conftest_path.read_text(encoding="utf-8") if conftest_path.exists() else None
    return module, conftest


def _parses(source):
    ast.parse(source)  # raises SyntaxError on broken output


# --- conftest generation --------------------------------------------------


def test_bearer_auth_extracted_to_conftest(tmp_path):
    module, conftest = _gen([_req(headers={"Authorization": "Bearer secret-token-123"})], tmp_path)
    assert conftest is not None
    _parses(conftest)
    assert "def auth_headers(" in conftest
    assert "Authorization" in conftest
    # scheme preserved, secret replaced with an env placeholder.
    assert 'f"Bearer {os.environ.get(' in conftest
    assert "AUTH_TOKEN" in conftest
    assert "secret-token-123" not in conftest


def test_secret_not_in_test_module(tmp_path):
    module, conftest = _gen([_req(headers={"Authorization": "Bearer secret-token-123"})], tmp_path)
    _parses(module)
    assert "secret-token-123" not in module
    # the test references the fixture rather than hardcoding the header.
    assert "auth_headers" in module
    assert "**auth_headers" in module


def test_non_auth_headers_stay_inline(tmp_path):
    module, conftest = _gen(
        [
            _req(
                headers={
                    "Authorization": "Bearer x",
                    "Accept": "application/json",
                }
            )
        ],
        tmp_path,
    )
    _parses(module)
    # non-auth header renders inline in the module, not in conftest.
    assert "Accept" in module
    assert "Accept" not in (conftest or "")


def test_no_auth_no_conftest(tmp_path):
    module, conftest = _gen([_req(headers={"Accept": "application/json"})], tmp_path)
    _parses(module)
    assert conftest is None
    assert "auth_headers" not in module


def test_basic_auth_scheme_preserved(tmp_path):
    _, conftest = _gen([_req(headers={"Authorization": "Basic dXNlcjpwYXNz"})], tmp_path)
    assert conftest is not None
    assert 'f"Basic {os.environ.get(' in conftest
    assert "dXNlcjpwYXNz" not in conftest


def test_api_key_header_extracted(tmp_path):
    _, conftest = _gen([_req(headers={"X-Api-Key": "abcd1234"})], tmp_path)
    assert conftest is not None
    _parses(conftest)
    assert "X-Api-Key" in conftest
    assert "X_API_KEY" in conftest
    assert "abcd1234" not in conftest


def test_env_token_in_auth_uses_os_environ(tmp_path):
    module, conftest = _gen([_req(headers={"Authorization": "Bearer ENV_token"})], tmp_path)
    assert conftest is not None
    _parses(conftest)
    # Postman variable becomes an os.environ lookup, never a literal or a
    # bare fixture reference (the fixture is self-contained in conftest).
    assert "os.environ.get('token'" in conftest
    assert "ENV_token" not in conftest
    assert "ENV_token" not in module


def test_auth_union_across_requests_single_entry(tmp_path):
    reqs = [
        _req(name="List", headers={"Authorization": "Bearer x"}),
        _req(name="Create", method="POST", headers={"Authorization": "Bearer x"}),
    ]
    module, conftest = _gen(reqs, tmp_path)
    _parses(module)
    _parses(conftest)
    # one shared Authorization entry, both tests take the fixture.
    assert conftest.count('"Authorization"') == 1
    assert module.count("auth_headers") >= 2


def test_raw_token_no_scheme_authorization(tmp_path):
    _, conftest = _gen([_req(headers={"Authorization": "abc123"})], tmp_path)
    assert conftest is not None
    _parses(conftest)
    assert "os.environ.get('AUTH_TOKEN', '')" in conftest
    assert 'f"Bearer' not in conftest
    assert "abc123" not in conftest


def test_mixed_case_authorization_deduped(tmp_path):
    reqs = [
        _req(name="A", headers={"Authorization": "Bearer x"}),
        _req(name="B", method="POST", headers={"authorization": "Bearer x"}),
    ]
    _, conftest = _gen(reqs, tmp_path)
    assert conftest is not None
    _parses(conftest)
    # one dict entry despite two casings; HTTP header names are case-insensitive.
    assert conftest.count('": f"Bearer') == 1


def test_proxy_authorization_extracted(tmp_path):
    module, conftest = _gen([_req(headers={"Proxy-Authorization": "Basic c2VjcmV0"})], tmp_path)
    assert conftest is not None
    _parses(conftest)
    assert "Proxy-Authorization" in conftest
    assert "c2VjcmV0" not in conftest
    assert "c2VjcmV0" not in module  # secret must not leak into the module


def test_adversarial_header_name_stays_safe(tmp_path):
    evil = "X-Api-Key\"; import os; os.system('x')  #"
    module, conftest = _gen([_req(headers={evil: "sekret"})], tmp_path)
    assert conftest is not None
    _parses(conftest)  # name is json-escaped as a dict key, cannot break out
    assert "sekret" not in conftest
    assert "sekret" not in module


def test_generated_files_compile_with_mixed_headers(tmp_path):
    module, conftest = _gen(
        [
            _req(
                headers={
                    "Authorization": "Bearer ENV_token",
                    "X-Api-Key": "k",
                    "Accept": "application/json",
                }
            )
        ],
        tmp_path,
    )
    _parses(module)
    _parses(conftest)
