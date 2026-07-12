"""Tests for core/openapi_parser.py (OpenAPI 3.x input support, issue #10)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

from core.generator import generate
from core.openapi_parser import parse_openapi

# --- Sample spec covering the three acceptance-criteria endpoints -------------


def _sample_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Sample API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "tags": ["users"],
                    "parameters": [
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
                "post": {
                    "operationId": "createUser",
                    "tags": ["users"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "age": {"type": "integer"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "created"}},
                },
            },
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "tags": ["users"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }


def _write_json(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


def _write_yaml(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return p


def _by_name(requests, method: str, url_fragment: str):
    for req in requests:
        if req.method == method.upper() and url_fragment in req.url:
            return req
    raise AssertionError(
        f"no {method} request with url fragment {url_fragment!r} in {[(r.method, r.url) for r in requests]}"
    )


# --- Core parsing ------------------------------------------------------------


def test_parse_openapi_returns_one_request_per_operation(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    assert len(reqs) == 3  # GET /users, POST /users, GET /users/{id}


def test_get_with_query_params(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    req = _by_name(reqs, "GET", "users?")
    assert req.method == "GET"
    # {{status}}/{{limit}} normalise to ENV_ tokens via ParsedRequest.url validator
    assert "ENV_status" in req.url
    assert "ENV_limit" in req.url
    assert req.body is None


def test_post_with_json_body(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    req = _by_name(reqs, "POST", "users")
    assert req.method == "POST"
    assert req.body is not None
    payload = json.loads(req.body)  # body is a raw JSON string, same shape as Postman path
    assert set(payload.keys()) == {"name", "age"}
    assert req.expected_status == 201


def test_get_with_path_param(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    req = _by_name(reqs, "GET", "users/ENV_id")
    assert req.method == "GET"
    assert "ENV_id" in req.url
    assert "{id}" not in req.url


def test_expected_status_defaults_to_200_when_no_2xx(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "x", "version": "1"},
        "paths": {"/ping": {"get": {"responses": {"default": {"description": "d"}}}}},
    }
    reqs = parse_openapi(_write_json(tmp_path, spec))
    assert reqs[0].expected_status == 200


def test_header_param_becomes_request_header(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "x", "version": "1"},
        "paths": {
            "/thing": {
                "get": {
                    "parameters": [
                        {"name": "X-Request-Id", "in": "header", "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    reqs = parse_openapi(_write_json(tmp_path, spec))
    assert "X-Request-Id" in reqs[0].headers
    # value must resolve to an ENV_ token, not the literal {{...}} placeholder,
    # so the generator renders it as an os.environ lookup
    assert reqs[0].headers["X-Request-Id"] == "ENV_X_Request_Id"
    out = tmp_path / "gen" / "test_api.py"
    generate(reqs, collection_name="x", output_path=out)
    assert "os.environ.get('X_Request_Id', '')" in out.read_text(encoding="utf-8")


def test_leading_path_param_survives_generation(tmp_path):
    # /{tenant}/users starts with a parameter; it must not be mistaken for a
    # base-URL variable and stripped by the generator.
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "x", "version": "1"},
        "paths": {
            "/{tenant}/users": {
                "get": {
                    "operationId": "listTenantUsers",
                    "parameters": [
                        {
                            "name": "tenant",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    reqs = parse_openapi(_write_json(tmp_path, spec))
    assert reqs[0].url == "{tenant}/users".replace("{tenant}", "ENV_tenant")
    out = tmp_path / "gen" / "test_api.py"
    generate(reqs, collection_name="x", output_path=out)
    text = out.read_text(encoding="utf-8")
    assert "os.environ.get('tenant', '')" in text  # param survived, not stripped
    assert "{BASE_URL}/users" not in text  # the buggy stripped form must not appear


# --- JSON and YAML both accepted ---------------------------------------------


def test_accepts_json_spec(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    assert len(reqs) == 3


def test_accepts_yaml_spec(tmp_path):
    reqs = parse_openapi(_write_yaml(tmp_path, _sample_spec()))
    assert len(reqs) == 3


def test_json_and_yaml_produce_identical_requests(tmp_path):
    from_json = parse_openapi(_write_json(tmp_path, _sample_spec()))
    from_yaml = parse_openapi(_write_yaml(tmp_path, _sample_spec()))
    assert [(r.method, r.url) for r in from_json] == [(r.method, r.url) for r in from_yaml]


# --- End-to-end: generated file is valid Python ------------------------------


def test_generated_output_is_valid_python(tmp_path):
    reqs = parse_openapi(_write_json(tmp_path, _sample_spec()))
    out = tmp_path / "generated" / "test_api.py"
    generate(reqs, collection_name="Sample API", output_path=out)
    ast.parse(out.read_text(encoding="utf-8"))  # raises SyntaxError if malformed


# --- Robustness --------------------------------------------------------------


def test_empty_paths_returns_empty_list(tmp_path):
    spec = {"openapi": "3.0.0", "info": {"title": "x", "version": "1"}, "paths": {}}
    assert parse_openapi(_write_json(tmp_path, spec)) == []


def test_non_object_root_raises(tmp_path):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError):
        parse_openapi(p)


def test_spec_title_reads_info_title(tmp_path):
    from core.openapi_parser import spec_title

    assert spec_title(_write_yaml(tmp_path, _sample_spec())) == "Sample API"


# --- CLI wiring --------------------------------------------------------------


def test_cli_input_format_openapi_end_to_end(tmp_path, monkeypatch, capsys):
    import main

    spec = _write_yaml(tmp_path, _sample_spec())
    out = tmp_path / "test_api.py"
    monkeypatch.setattr(
        "sys.argv",
        [
            "postman2pytest",
            "--collection",
            str(spec),
            "--input-format",
            "openapi",
            "--out",
            str(out),
        ],
    )
    assert main.main() == 0
    assert out.exists()
    ast.parse(out.read_text(encoding="utf-8"))
    assert "3 test(s)" in capsys.readouterr().out


def test_cli_default_input_format_is_postman(tmp_path, monkeypatch):
    import main

    collection = tmp_path / "c.json"
    collection.write_text(
        json.dumps(
            {
                "info": {
                    "name": "C",
                    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                },
                "item": [
                    {
                        "name": "ping",
                        "request": {
                            "method": "GET",
                            "header": [],
                            "url": {"raw": "{{base_url}}/ping"},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.py"
    monkeypatch.setattr(
        "sys.argv", ["postman2pytest", "--collection", str(collection), "--out", str(out)]
    )
    assert main.main() == 0  # default path (postman) still works, no --input-format given
    assert out.exists()
