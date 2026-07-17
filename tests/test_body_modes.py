"""Form-data and urlencoded request body support (Roadmap #1).

Postman bodies in mode "urlencoded" / "formdata" carry structured key-value
fields, not a raw string. The parser must capture them and the generator must
render them as a `data={...}` argument (form encoding) instead of `json=`.
"""

import json
from pathlib import Path

from core.generator import generate
from core.parser import ParsedRequest, parse_collection


def _write_collection(tmp_path: Path, body: dict) -> Path:
    collection = {
        "info": {
            "name": "API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "Token",
                "request": {
                    "method": "POST",
                    "url": {"raw": "https://api.example.com/token"},
                    "body": body,
                },
            }
        ],
    }
    p = tmp_path / "c.postman_collection.json"
    p.write_text(json.dumps(collection), encoding="utf-8")
    return p


# Parser


def test_parser_reads_urlencoded_fields(tmp_path):
    body = {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "grant_type", "value": "password"},
            {"key": "username", "value": "alice"},
        ],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert len(reqs) == 1
    assert reqs[0].body_mode == "urlencoded"
    assert reqs[0].form_fields == {"grant_type": "password", "username": "alice"}


def test_parser_reads_formdata_text_fields(tmp_path):
    body = {
        "mode": "formdata",
        "formdata": [{"key": "title", "value": "hello", "type": "text"}],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].body_mode == "formdata"
    assert reqs[0].form_fields == {"title": "hello"}


def test_parser_skips_disabled_form_fields(tmp_path):
    body = {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "keep", "value": "1"},
            {"key": "drop", "value": "2", "disabled": True},
        ],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields == {"keep": "1"}


# Generator


def _gen(tmp_path, req) -> str:
    out = tmp_path / "test_api.py"
    generate([req], collection_name="API", output_path=out)
    return out.read_text(encoding="utf-8")


def _form_req(**overrides) -> ParsedRequest:
    defaults = dict(
        name="Token",
        method="POST",
        url="ENV_base_url/token",
        headers={},
        body=None,
        expected_status=200,
        folder=None,
    )
    defaults.update(overrides)
    return ParsedRequest(**defaults)


def test_generate_urlencoded_uses_data_not_json(tmp_path):
    req = _form_req(body_mode="urlencoded", form_fields={"grant_type": "password"})
    content = _gen(tmp_path, req)
    assert "json=body" not in content
    assert "data=" in content
    assert "grant_type" in content
    assert "password" in content


def test_generate_formdata_uses_data(tmp_path):
    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        form_fields={"title": "hello"},
    )
    content = _gen(tmp_path, req)
    assert "data=" in content
    assert "title" in content


# Edge cases (characterise reviewed behaviour, guard regressions)


def test_parser_substitutes_vars_in_form_values(tmp_path):
    body = {"mode": "urlencoded", "urlencoded": [{"key": "token", "value": "{{access_token}}"}]}
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert "{{" not in reqs[0].form_fields["token"]


def test_parser_formdata_file_only_falls_back_to_no_body(tmp_path):
    body = {"mode": "formdata", "formdata": [{"key": "f", "type": "file", "src": "x.png"}]}
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields is None
    assert reqs[0].body_mode == "raw"


def test_parser_duplicate_urlencoded_keys_preserved(tmp_path):
    # Repeated keys keep every value. A dict cannot hold duplicates, so the
    # parser falls back to a list of (key, value) pairs, which requests sends
    # as multiple fields with the same name.
    body = {
        "mode": "urlencoded",
        "urlencoded": [{"key": "scope", "value": "read"}, {"key": "scope", "value": "write"}],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields == [("scope", "read"), ("scope", "write")]


def test_parser_unique_keys_stay_dict(tmp_path):
    # Without duplicates the parser keeps the idiomatic dict form.
    body = {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "grant_type", "value": "password"},
            {"key": "scope", "value": "read"},
        ],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields == {"grant_type": "password", "scope": "read"}


def test_generate_duplicate_keys_output_compiles_and_keeps_values(tmp_path):
    import py_compile

    req = _form_req(
        body_mode="urlencoded",
        form_fields=[("scope", "read"), ("scope", "write")],
    )
    out = tmp_path / "test_api.py"
    generate([req], collection_name="API", output_path=out)
    py_compile.compile(str(out), doraise=True)  # raises SyntaxError if invalid
    content = out.read_text(encoding="utf-8")
    assert "data=" in content
    assert content.count('"scope"') == 2
    assert '"read"' in content and '"write"' in content


def test_generate_urlencoded_output_compiles(tmp_path):
    import py_compile

    req = _form_req(
        body_mode="urlencoded", form_fields={"grant_type": "password", "scope": "read write"}
    )
    out = tmp_path / "test_api.py"
    generate([req], collection_name="API", output_path=out)
    py_compile.compile(str(out), doraise=True)  # raises SyntaxError if invalid
