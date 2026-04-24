"""Tests for core/parser.py"""
import json
import textwrap
from pathlib import Path

import pytest

from core.parser import parse_collection, _replace_vars, _extract_status


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_collection(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "collection.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _minimal_collection(items: list) -> dict:
    return {
        "info": {
            "name": "Test Collection",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }


def _simple_request(name: str, method: str = "GET", url: str = "{{base_url}}/api") -> dict:
    return {
        "name": name,
        "request": {
            "method": method,
            "header": [],
            "url": {"raw": url},
        },
    }


# ── _replace_vars ─────────────────────────────────────────────────────────────

def test_replace_vars_substitutes_postman_variable():
    assert _replace_vars("{{base_url}}/api") == "ENV_base_url/api"


def test_replace_vars_multiple_variables():
    result = _replace_vars("{{host}}/{{version}}/users")
    assert "ENV_host" in result
    assert "ENV_version" in result


def test_replace_vars_no_variables():
    assert _replace_vars("http://localhost/api") == "http://localhost/api"


# ── _extract_status ───────────────────────────────────────────────────────────

def test_extract_status_finds_code():
    events = [{"listen": "test", "script": {"exec": ["pm.response.to.have.status(201);"]}}]
    assert _extract_status(events) == 201


def test_extract_status_returns_none_when_absent():
    events = [{"listen": "test", "script": {"exec": ["pm.test('ok', () => {});"]}}]
    assert _extract_status(events) is None


def test_extract_status_ignores_prerequest_events():
    events = [{"listen": "prerequest", "script": {"exec": ["pm.response.to.have.status(500);"]}}]
    assert _extract_status(events) is None


# ── parse_collection ──────────────────────────────────────────────────────────

def test_parse_single_get_request(tmp_path):
    col = _minimal_collection([_simple_request("Get users", "GET", "{{base_url}}/users")])
    requests = parse_collection(_write_collection(tmp_path, col))
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert "ENV_base_url" in requests[0].url


def test_parse_post_with_body(tmp_path):
    item = {
        "name": "Create user",
        "request": {
            "method": "POST",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {"mode": "raw", "raw": '{"name": "John"}'},
            "url": {"raw": "{{base_url}}/users"},
        },
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([item])))
    assert requests[0].method == "POST"
    assert requests[0].body == '{"name": "John"}'
    assert requests[0].headers["Content-Type"] == "application/json"


def test_parse_nested_folder(tmp_path):
    folder = {
        "name": "Users",
        "item": [_simple_request("List"), _simple_request("Detail")],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    assert len(requests) == 2
    assert all(r.folder == "users" for r in requests)


def test_parse_expected_status_from_test_script(tmp_path):
    item = _simple_request("Create")
    item["event"] = [{"listen": "test", "script": {"exec": ["pm.response.to.have.status(201);"]}}]
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([item])))
    assert requests[0].expected_status == 201


def test_parse_default_status_200(tmp_path):
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([_simple_request("X")])))
    assert requests[0].expected_status == 200


def test_parse_empty_collection(tmp_path):
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([])))
    assert requests == []


def test_parse_skips_malformed_item(tmp_path):
    items = [{"name": "broken", "request": None}, _simple_request("Good")]
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection(items)))
    assert len(requests) == 1
    assert requests[0].name == "Good"


def test_parse_disabled_headers_excluded(tmp_path):
    item = {
        "name": "Test",
        "request": {
            "method": "GET",
            "header": [
                {"key": "X-Active", "value": "yes"},
                {"key": "X-Disabled", "value": "no", "disabled": True},
            ],
            "url": {"raw": "{{base_url}}/api"},
        },
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([item])))
    assert "X-Active" in requests[0].headers
    assert "X-Disabled" not in requests[0].headers


def test_test_name_slug_format(tmp_path):
    requests = parse_collection(
        _write_collection(tmp_path, _minimal_collection([_simple_request("Get All Users!", "POST")]))
    )
    name = requests[0].test_name
    assert name.startswith("test_")
    assert " " not in name
    assert "!" not in name
