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


def test_parser_formdata_file_only_captured_as_file_fields(tmp_path):
    # A file-only formdata body is now a multipart upload, not an empty body.
    # The file field is captured separately so the generator renders `files=`.
    body = {"mode": "formdata", "formdata": [{"key": "f", "type": "file", "src": "x.png"}]}
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields is None
    assert reqs[0].file_fields == [("f", "x.png")]
    assert reqs[0].body_mode == "formdata"


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


# Formdata file upload (Roadmap #1 - multipart files=)


def test_parser_formdata_mixed_text_and_file(tmp_path):
    # A formdata body mixing text and file fields splits them: text fields go to
    # form_fields (data=), file fields to file_fields (files=).
    body = {
        "mode": "formdata",
        "formdata": [
            {"key": "title", "value": "hello", "type": "text"},
            {"key": "document", "type": "file", "src": "report.pdf"},
        ],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].form_fields == {"title": "hello"}
    assert reqs[0].file_fields == [("document", "report.pdf")]


def test_parser_formdata_file_src_basename_from_path(tmp_path):
    # The default filename is the basename of the source path, so an absolute
    # path on the collection author's machine does not leak into generated code.
    body = {
        "mode": "formdata",
        "formdata": [{"key": "avatar", "type": "file", "src": "C:\\\\Users\\\\alice\\\\pic.png"}],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].file_fields == [("avatar", "pic.png")]


def test_parser_formdata_file_src_list_expands(tmp_path):
    # Postman allows a list of sources under one file key (multiple uploads).
    body = {
        "mode": "formdata",
        "formdata": [{"key": "docs", "type": "file", "src": ["a.pdf", "b.pdf"]}],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].file_fields == [("docs", "a.pdf"), ("docs", "b.pdf")]


def test_parser_formdata_file_no_src_defaults_to_key(tmp_path):
    # A file field with no src still needs a filename hint; fall back to the key.
    body = {"mode": "formdata", "formdata": [{"key": "upload", "type": "file"}]}
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].file_fields == [("upload", "upload")]


def test_parser_formdata_file_src_list_with_null_falls_back_to_key(tmp_path):
    # A null entry inside a src list is not a string; it falls back to the key
    # rather than crashing or emitting an empty filename.
    body = {
        "mode": "formdata",
        "formdata": [{"key": "docs", "type": "file", "src": ["a.pdf", None]}],
    }
    reqs = parse_collection(_write_collection(tmp_path, body))
    assert reqs[0].file_fields == [("docs", "a.pdf"), ("docs", "docs")]


def test_generate_file_env_name_sanitizes_key_with_space(tmp_path):
    # A key with a space/punctuation maps to an upper snake-case env var, so the
    # generated os.environ lookup is a valid, predictable name.
    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        file_fields=[("profile pic", "me.png")],
    )
    content = _gen(tmp_path, req)
    assert 'os.environ.get("PROFILE_PIC_FILE", "me.png")' in content


def test_generate_formdata_file_renders_files_open_env(tmp_path):
    # A file field renders a files= argument whose path is an env placeholder
    # defaulting to the basename, mirroring how auth secrets stay out of source.
    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        file_fields=[("document", "report.pdf")],
    )
    content = _gen(tmp_path, req)
    assert "files=" in content
    assert 'os.environ.get("DOCUMENT_FILE", "report.pdf")' in content
    assert '"rb"' in content


def test_generate_formdata_mixed_data_and_files(tmp_path):
    # Text plus file fields must send BOTH data= and files= on the same request.
    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        form_fields={"title": "hello"},
        file_fields=[("document", "report.pdf")],
    )
    content = _gen(tmp_path, req)
    assert "data=data" in content
    assert "files=files" in content
    assert "json=body" not in content


def test_generate_formdata_file_output_compiles(tmp_path):
    import py_compile

    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        file_fields=[("document", "report.pdf")],
    )
    out = tmp_path / "test_api.py"
    generate([req], collection_name="API", output_path=out)
    py_compile.compile(str(out), doraise=True)  # raises SyntaxError if invalid


def test_generate_duplicate_file_keys_list_form_compiles(tmp_path):
    import py_compile

    # Repeated file keys cannot live in a dict; the generator emits the
    # list-of-tuples files= form so every upload is preserved.
    req = _form_req(
        name="Upload",
        url="ENV_base_url/upload",
        body_mode="formdata",
        file_fields=[("docs", "a.pdf"), ("docs", "b.pdf")],
    )
    out = tmp_path / "test_api.py"
    generate([req], collection_name="API", output_path=out)
    py_compile.compile(str(out), doraise=True)
    content = out.read_text(encoding="utf-8")
    assert content.count('"docs"') == 2
    assert '"a.pdf"' in content and '"b.pdf"' in content
