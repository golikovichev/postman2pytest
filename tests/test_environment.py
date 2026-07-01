"""Tests for core/environment.py - Postman environment variable resolution."""

import json
from pathlib import Path

import pytest

from core.environment import Environment, load_environment

# -- from_postman_export: parsing the Postman environment export shape --


def test_parses_enabled_non_secret_values():
    data = {
        "name": "My Env",
        "values": [
            {
                "key": "base_url",
                "value": "https://api.example.com",
                "enabled": True,
                "type": "default",
            },
        ],
    }
    env = Environment.from_postman_export(data)
    assert env.inline_value("base_url") == "https://api.example.com"


def test_disabled_value_is_ignored():
    data = {
        "values": [
            {"key": "base_url", "value": "https://old", "enabled": False, "type": "default"},
        ],
    }
    env = Environment.from_postman_export(data)
    # disabled -> not known -> not inlined -> becomes a fixture
    assert env.inline_value("base_url") is None


def test_missing_enabled_defaults_to_enabled():
    # Postman sometimes omits "enabled" for active variables.
    data = {"values": [{"key": "base_url", "value": "https://api", "type": "default"}]}
    env = Environment.from_postman_export(data)
    assert env.inline_value("base_url") == "https://api"


def test_secret_typed_value_is_never_inlined():
    data = {
        "values": [
            {"key": "auth_token", "value": "s3cr3t", "enabled": True, "type": "secret"},
        ],
    }
    env = Environment.from_postman_export(data)
    # secret value must NOT leak into generated source -> resolves to a fixture
    assert env.inline_value("auth_token") is None
    assert env.is_secret("auth_token") is True


def test_unknown_variable_is_not_inlined():
    env = Environment.from_postman_export({"values": []})
    assert env.inline_value("whatever") is None
    assert env.is_secret("whatever") is False


def test_missing_values_key_yields_empty_env():
    env = Environment.from_postman_export({"name": "empty"})
    assert env.inline_value("base_url") is None


def test_blank_or_missing_key_entries_are_skipped():
    data = {"values": [{"value": "x", "enabled": True}, {"key": "", "value": "y"}]}
    env = Environment.from_postman_export(data)
    assert env.inline_value("") is None


# -- needs_fixture: which {{vars}} become named pytest fixtures --


def test_needs_fixture_for_secret_and_unknown_but_not_for_inlined():
    data = {
        "values": [
            {"key": "base_url", "value": "https://api", "enabled": True, "type": "default"},
            {"key": "auth_token", "value": "s3cr3t", "enabled": True, "type": "secret"},
        ],
    }
    env = Environment.from_postman_export(data)
    assert env.needs_fixture("base_url") is False  # inlined
    assert env.needs_fixture("auth_token") is True  # secret -> fixture
    assert env.needs_fixture("missing") is True  # unknown -> fixture


# -- load_environment: file loading --


def test_load_environment_reads_json_file(tmp_path: Path):
    p = tmp_path / "env.json"
    p.write_text(
        json.dumps({"values": [{"key": "base_url", "value": "https://x", "enabled": True}]}),
        encoding="utf-8",
    )
    env = load_environment(p)
    assert env.inline_value("base_url") == "https://x"


def test_load_environment_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_environment(tmp_path / "nope.json")


# -- generator wiring: env-aware ENV_xxx rendering --


def _env(values):
    from core.environment import Environment as _E

    return _E.from_postman_export({"values": values})


def test_render_url_inlines_non_secret_value():
    from core.generator import _render_url

    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = _render_url("ENV_base_url/users", env)
    assert "https://api.example.com/users" in out
    assert "os.environ" not in out


def test_render_url_unknown_path_var_becomes_fixture_ref():
    from core.generator import _render_url

    # with --env, an unknown mid-path var becomes a bare fixture reference
    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = _render_url("path/ENV_ver/users", env)  # relative, base_url not the prefix here
    assert "{ver}" in out
    assert "os.environ" not in out


def test_render_secret_value_becomes_fixture_ref_not_inlined():
    from core.generator import _render_header_value

    env = _env([{"key": "token", "value": "s3cr3t", "enabled": True, "type": "secret"}])
    out = _render_header_value("Bearer ENV_token", env)
    assert "s3cr3t" not in out  # secret never inlined into source
    assert "{token}" in out  # secret resolves to a fixture, not inline os.environ
    assert "os.environ" not in out


def test_render_header_inlines_non_secret_value():
    from core.generator import _render_header_value

    env = _env([{"key": "ver", "value": "v2", "enabled": True}])
    out = _render_header_value("ENV_ver", env)
    assert out == '"v2"'
    assert "os.environ" not in out


def test_render_header_unknown_becomes_fixture_ref():
    from core.generator import _render_header_value

    env = _env([])  # var not in env -> fixture
    out = _render_header_value("Bearer ENV_token", env)
    assert "{token}" in out
    assert "os.environ" not in out


def test_render_without_env_is_unchanged_backward_compatible():
    from core.generator import _render_url

    out = _render_url("path/ENV_ver/users", None)
    assert "os.environ.get('ver'" in out


# -- Part B: fixture generation end to end --


def _collection_with_vars():
    return {
        "info": {
            "name": "C",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "get user",
                "request": {
                    "method": "GET",
                    "url": {"raw": "{{base_url}}/users"},
                    "header": [
                        {"key": "Authorization", "value": "Bearer {{auth_token}}"},
                        {"key": "X-Api-Version", "value": "{{api_ver}}"},
                    ],
                },
            }
        ],
    }


def test_generate_emits_fixtures_for_secret_and_unknown(tmp_path: Path):
    from core.generator import generate
    from core.parser import parse_collection

    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(_collection_with_vars()), encoding="utf-8")
    reqs = parse_collection(cpath)
    env = _env(
        [
            {"key": "base_url", "value": "https://api.example.com", "enabled": True},
            {"key": "auth_token", "value": "SUPERSECRET", "enabled": True, "type": "secret"},
        ]
    )  # api_ver is unknown -> fixture
    out = tmp_path / "t.py"
    generate(reqs, collection_name="C", output_path=out, postman_env=env)
    text = out.read_text(encoding="utf-8")

    conftest = (out.parent / "conftest.py").read_text(encoding="utf-8")
    # Authorization is centralised in auth_headers (conftest), so its secret var
    # is an os.environ lookup there, not a module fixture.
    assert "def auth_token():" not in text
    assert "os.environ.get('auth_token'" in conftest
    assert "def api_ver():" in text  # unknown non-auth var -> module fixture
    assert "SUPERSECRET" not in text  # secret value never inlined
    assert "SUPERSECRET" not in conftest
    assert "https://api.example.com/users" in text  # non-secret inlined
    # the test takes its module fixtures plus the shared auth_headers fixture
    assert "(api_ver, auth_headers):" in text
    # both generated files are valid Python
    compile(text, str(out), "exec")
    compile(conftest, str(out.parent / "conftest.py"), "exec")


def test_generate_without_env_emits_no_fixtures(tmp_path: Path):
    from core.generator import generate
    from core.parser import parse_collection

    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(_collection_with_vars()), encoding="utf-8")
    reqs = parse_collection(cpath)
    out = tmp_path / "t.py"
    generate(reqs, collection_name="C", output_path=out, postman_env=None)
    text = out.read_text(encoding="utf-8")

    conftest = (out.parent / "conftest.py").read_text(encoding="utf-8")
    assert "@pytest.fixture" not in text  # legacy path: module has no fixtures
    # non-auth var stays inline in the module; the auth var lives in the fixture.
    assert "os.environ.get('api_ver'" in text
    assert "os.environ.get('auth_token'" in conftest
    assert "auth_token" not in text  # auth var moved to the fixture
    compile(text, str(out), "exec")
    compile(conftest, str(out.parent / "conftest.py"), "exec")


def test_render_url_inlined_base_with_path_var_keeps_var_as_fixture():
    # regression: inlining base_url made the URL absolute, which short-circuited
    # to json.dumps and leaked any remaining {{var}} as a raw ENV_xxx token.
    from core.generator import _render_url

    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = _render_url("ENV_base_url/orders/ENV_region", env)
    assert "ENV_region" not in out  # raw token must never leak
    assert "{region}" in out  # region -> fixture reference
    assert "https://api.example.com/orders/" in out


def test_collect_fixtures_includes_path_var_after_inlined_base(tmp_path: Path):
    from core.generator import generate
    from core.parser import parse_collection

    col = {
        "info": {
            "name": "C",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "list",
                "request": {"method": "GET", "url": {"raw": "{{base_url}}/orders/{{region}}"}},
            }
        ],
    }
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(col), encoding="utf-8")
    reqs = parse_collection(cpath)
    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = tmp_path / "t.py"
    generate(reqs, collection_name="C", output_path=out, postman_env=env)
    text = out.read_text(encoding="utf-8")
    assert "def region():" in text
    assert "(region):" in text
    # the executable URL resolves the path var to the fixture, not a raw token
    assert 'url = f"https://api.example.com/orders/{region}"' in text
    compile(text, str(out), "exec")


# -- safe fixture names (review M1 / Mi1) --


def test_non_identifier_var_name_falls_back_and_compiles(tmp_path: Path):
    from core.generator import generate
    from core.parser import parse_collection

    col = {
        "info": {
            "name": "C",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "mfa",
                "request": {"method": "GET", "url": {"raw": "{{base_url}}/login/{{2fa}}"}},
            }
        ],
    }
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(col), encoding="utf-8")
    reqs = parse_collection(cpath)
    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = tmp_path / "t.py"
    generate(reqs, collection_name="C", output_path=out, postman_env=env)
    text = out.read_text(encoding="utf-8")

    assert "def 2fa():" not in text  # not a (invalid) fixture
    assert "os.environ.get('2fa'" in text  # safe os.environ fallback
    compile(text, str(out), "exec")  # must be valid Python


def test_reserved_name_var_does_not_become_fixture(tmp_path: Path):
    from core.generator import generate
    from core.parser import parse_collection

    col = {
        "info": {
            "name": "C",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "r",
                "request": {
                    "method": "GET",
                    "url": {"raw": "{{base_url}}/x"},
                    "header": [{"key": "X-Url", "value": "{{url}}"}],
                },
            }
        ],
    }
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(col), encoding="utf-8")
    reqs = parse_collection(cpath)
    env = _env([{"key": "base_url", "value": "https://api.example.com", "enabled": True}])
    out = tmp_path / "t.py"
    generate(reqs, collection_name="C", output_path=out, postman_env=env)
    text = out.read_text(encoding="utf-8")

    # 'url' would shadow the local url variable -> routed to os.environ instead
    assert "os.environ.get('url'" in text
    compile(text, str(out), "exec")


def test_load_environment_malformed_json_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_environment(p)
