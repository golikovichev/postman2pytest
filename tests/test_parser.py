"""Tests for core/parser.py"""

import json
import re
from pathlib import Path

from core.parser import _extract_status, _replace_vars, _slugify, parse_collection
from main import filter_requests_by_folder

# Helpers


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


# _replace_vars


def test_replace_vars_substitutes_postman_variable():
    assert _replace_vars("{{base_url}}/api") == "ENV_base_url/api"


def test_replace_vars_multiple_variables():
    result = _replace_vars("{{host}}/{{version}}/users")
    assert "ENV_host" in result
    assert "ENV_version" in result


def test_replace_vars_no_variables():
    assert _replace_vars("http://localhost/api") == "http://localhost/api"


# _extract_status


def test_extract_status_finds_code():
    events = [{"listen": "test", "script": {"exec": ["pm.response.to.have.status(201);"]}}]
    assert _extract_status(events) == 201


def test_extract_status_returns_none_when_absent():
    events = [{"listen": "test", "script": {"exec": ["pm.test('ok', () => {});"]}}]
    assert _extract_status(events) is None


def test_extract_status_ignores_prerequest_events():
    events = [{"listen": "prerequest", "script": {"exec": ["pm.response.to.have.status(500);"]}}]
    assert _extract_status(events) is None


# Parse_collection


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


def test_filter_requests_by_folder_keeps_matching_folder(tmp_path):
    items = [
        {"name": "Users", "item": [_simple_request("List users")]},
        {"name": "Orders", "item": [_simple_request("List orders")]},
    ]
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection(items)))
    filtered = filter_requests_by_folder(requests, "orders")
    assert [request.name for request in filtered] == ["List orders"]


def test_filter_requests_by_folder_is_case_insensitive(tmp_path):
    folder = {"name": "Orders", "item": [_simple_request("List orders")]}
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    filtered = filter_requests_by_folder(requests, "ORDERS")
    assert len(filtered) == 1


def test_filter_requests_by_folder_unknown_returns_empty(tmp_path):
    folder = {"name": "Orders", "item": [_simple_request("List orders")]}
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    assert filter_requests_by_folder(requests, "users") == []


def test_parse_expected_status_from_test_script(tmp_path):
    item = _simple_request("Create")
    item["event"] = [{"listen": "test", "script": {"exec": ["pm.response.to.have.status(201);"]}}]
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([item])))
    assert requests[0].expected_status == 201


def test_parse_default_status_200(tmp_path):
    requests = parse_collection(
        _write_collection(tmp_path, _minimal_collection([_simple_request("X")]))
    )
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
        _write_collection(
            tmp_path, _minimal_collection([_simple_request("Get All Users!", "POST")])
        )
    )
    name = requests[0].test_name
    assert name.startswith("test_")
    assert " " not in name
    assert "!" not in name


# _slugify


def test_slugify_ascii_passthrough():
    assert _slugify("Get Users") == "get_users"


def test_slugify_strips_punctuation():
    assert _slugify("Get All Users!") == "get_all_users"


def test_slugify_cyrillic_transliterates():
    assert _slugify("Заказы") == "zakazy"


def test_slugify_chinese_transliterates():
    # unidecode renders the two ideograms as separate pinyin tokens
    result = _slugify("订单")
    assert result and result != "unnamed"
    assert re.match(r"^[a-z0-9_]+$", result)


def test_slugify_accented_latin_transliterates():
    assert _slugify("Café Münchën") == "cafe_munchen"


def test_slugify_empty_returns_unnamed():
    assert _slugify("") == "unnamed"


def test_slugify_only_punctuation_returns_unnamed():
    assert _slugify("!!!---") == "unnamed"


# Non-ASCII folder and disambiguation (issue #3)


def test_parse_cyrillic_folder_produces_ascii_test_name(tmp_path):
    folder = {
        "name": "Заказы",
        "item": [_simple_request("Create", "POST")],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    assert requests[0].test_name == "test_zakazy_post_create"


def test_parse_collision_appends_numeric_suffix(tmp_path):
    # Four requests in the same folder, all POST, all named "" (Postman
    # collections produced by some tools omit the name field). Before the
    # fix this produced four identical test_post functions and pytest only
    # collected one. After the fix each gets a numeric suffix.
    folder = {
        "name": "Orders",
        "item": [
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/a"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/b"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/c"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/d"}}},
        ],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    names = [r.test_name for r in requests]
    assert len(set(names)) == 4, f"Expected unique names, got {names}"
    assert names == [
        "test_orders_post_unnamed_1",
        "test_orders_post_unnamed_2",
        "test_orders_post_unnamed_3",
        "test_orders_post_unnamed_4",
    ]


def test_parse_no_collision_leaves_names_clean(tmp_path):
    folder = {
        "name": "Users",
        "item": [_simple_request("List", "GET"), _simple_request("Create", "POST")],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    # No suffixes when there is no collision
    assert requests[0].test_name == "test_users_get_list"
    assert requests[1].test_name == "test_users_post_create"


def test_parse_cyrillic_folder_and_collision_combined(tmp_path):
    # Regression for the exact issue #3 reproduction: Cyrillic folder name
    # plus several requests sharing method and missing name field. Before
    # the fix the folder slug was empty and all functions reduced to test_post.
    folder = {
        "name": "Заказы",
        "item": [
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/x"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/y"}}},
        ],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    names = [r.test_name for r in requests]
    assert len(set(names)) == 2
    assert all(n.startswith("test_zakazy_post_unnamed_") for n in names)


def test_parse_emits_warning_on_disambiguation(tmp_path, caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="core.parser")
    folder = {
        "name": "X",
        "item": [
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/a"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/b"}}},
        ],
    }
    parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("Disambiguating" in r.message for r in warnings)


# Coverage gap closers (added 2026-05-19)


def test_folder_with_unsluggable_name_becomes_empty(tmp_path):
    """Folder name that slugifies to 'unnamed' is treated as no folder.

    Covers parser.py L107: `if folder_name == "unnamed": folder_name = ""`.
    """
    folder = {
        "name": "?",  # _slugify('?') → 'unnamed'
        "item": [_simple_request("List users", url="/users")],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    assert len(requests) == 1
    assert requests[0].folder is None


def test_malformed_request_skipped_with_warning(tmp_path, caplog):
    """Item that raises TypeError during parse is skipped with a warning.

    Covers parser.py L149-150: `except (KeyError, TypeError, ValueError)` branch.
    Header with non-string value triggers re.sub TypeError inside _replace_vars.

    Brittleness note: if `_replace_vars` ever coerces values via `str(value)`,
    this specific TypeError trigger stops firing and the request will parse
    successfully. The assertion below (`len(requests) == 1` + only 'Good'
    survives) would fail loudly in that case. Replace this trigger with
    another shape that still raises one of (KeyError, TypeError, ValueError)
    inside the try block. Candidates: header element with non-dict shape
    (e.g. `"header": ["not-a-dict"]` -> `h.get("key")` raises AttributeError.
    Note that AttributeError is NOT caught here, so it would need a different
    fix), or set `"event": "not-a-list"` so `_extract_status` iteration fails.
    """
    import logging

    caplog.set_level(logging.WARNING, logger="core.parser")
    bad_item = {
        "name": "Bad header value",
        "request": {
            "method": "GET",
            "header": [{"key": "X-Bad", "value": 12345}],  # int, not str
            "url": {"raw": "/api"},
        },
    }
    good_item = _simple_request("Good", url="/ok")
    requests = parse_collection(
        _write_collection(tmp_path, _minimal_collection([bad_item, good_item]))
    )
    # Good request survives, bad one is skipped
    assert len(requests) == 1
    assert requests[0].name == "Good"
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("Skipping item 'Bad header value'" in r.message for r in warnings)


def test_disambiguate_preserves_non_colliding_names(tmp_path):
    """When some requests collide and others do not, non-colliding keep their base.

    Covers parser.py L189-190: `if base not in duplicates: req.final_test_name = base; continue`.
    """
    folder = {
        "name": "API",
        "item": [
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/a"}}},
            {"name": "", "request": {"method": "POST", "header": [], "url": {"raw": "/b"}}},
            _simple_request("Unique", url="/unique"),
        ],
    }
    requests = parse_collection(_write_collection(tmp_path, _minimal_collection([folder])))
    assert len(requests) == 3
    names = [r.test_name for r in requests]
    # The unique one has no suffix; the two colliding ones get _1 and _2.
    unique_match = [n for n in names if n.endswith("unique")]
    suffixed = [n for n in names if re.search(r"_\d+$", n)]
    assert len(unique_match) == 1
    assert len(suffixed) == 2


def test_unknown_schema_logs_warning(tmp_path, caplog):
    """Schema other than v2.0/v2.1 logs a warning but still parses.

    Covers parser.py L205: `logger.warning("Unexpected collection schema: %s. ...")`.
    """
    import logging

    caplog.set_level(logging.WARNING, logger="core.parser")
    data = {
        "info": {
            "name": "Weird",
            "schema": "https://schema.getpostman.com/json/collection/v3.0.0/collection.json",
        },
        "item": [_simple_request("Anything", url="/x")],
    }
    requests = parse_collection(_write_collection(tmp_path, data))
    assert len(requests) == 1
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("Unexpected collection schema" in r.message for r in warnings)
