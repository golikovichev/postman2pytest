"""
Tests for Postman test-script assertion translation.

Postman collections carry post-response test scripts (pm.test(...)) that assert
on the response. Earlier versions emitted only the request and a status check,
dropping every other assertion. These tests cover the supported subset:
response time, header presence, and JSON body field equality. Patterns that are
not recognised must be skipped silently (no broken assert emitted).
"""

from __future__ import annotations

from pathlib import Path

from core.parser import Assertion, _extract_assertions, _parse_js_value, parse_collection


def _test_events(*lines: str) -> list[dict]:
    """Wrap raw JS lines into a Postman 'test' event list."""
    return [{"listen": "test", "script": {"exec": list(lines)}}]


# --- _parse_js_value -----------------------------------------------------


def test_parse_js_value_double_quoted_string():
    assert _parse_js_value('"John"') == "John"


def test_parse_js_value_single_quoted_string():
    assert _parse_js_value("'active'") == "active"


def test_parse_js_value_integer():
    assert _parse_js_value("42") == 42


def test_parse_js_value_float():
    assert _parse_js_value("3.14") == 3.14


def test_parse_js_value_true():
    assert _parse_js_value("true") is True


def test_parse_js_value_false():
    assert _parse_js_value("false") is False


def test_parse_js_value_unrecognised_returns_none():
    assert _parse_js_value("someVariable") is None


# --- _extract_assertions: response time ----------------------------------


def test_extract_response_time_below():
    events = _test_events(
        'pm.test("fast", function () {',
        "  pm.expect(pm.response.responseTime).to.be.below(500);",
        "});",
    )
    result = _extract_assertions(events)
    assert result == [Assertion(kind="response_time_below", value=500)]


# --- _extract_assertions: header presence --------------------------------


def test_extract_header_present_double_quotes():
    events = _test_events('pm.response.to.have.header("Content-Type");')
    result = _extract_assertions(events)
    assert result == [Assertion(kind="header_present", target="Content-Type")]


def test_extract_header_present_single_quotes():
    events = _test_events("pm.response.to.have.header('X-Request-Id');")
    result = _extract_assertions(events)
    assert result == [Assertion(kind="header_present", target="X-Request-Id")]


# --- _extract_assertions: JSON body field equality -----------------------


def test_extract_json_field_string_jsondata_idiom():
    events = _test_events(
        "var jsonData = pm.response.json();",
        'pm.expect(jsonData.name).to.eql("John");',
    )
    result = _extract_assertions(events)
    assert result == [Assertion(kind="json_field_equals", target="name", value="John")]


def test_extract_json_field_uses_pm_response_json_idiom():
    events = _test_events('pm.expect(pm.response.json().status).to.eql("active");')
    result = _extract_assertions(events)
    assert result == [Assertion(kind="json_field_equals", target="status", value="active")]


def test_extract_json_field_number_with_equal():
    events = _test_events("pm.expect(jsonData.id).to.equal(42);")
    result = _extract_assertions(events)
    assert result == [Assertion(kind="json_field_equals", target="id", value=42)]


def test_extract_json_field_boolean():
    events = _test_events("pm.expect(jsonData.active).to.eql(true);")
    result = _extract_assertions(events)
    assert result == [Assertion(kind="json_field_equals", target="active", value=True)]


# --- _extract_assertions: combinations and edge cases --------------------


def test_extract_multiple_assertions_in_one_script():
    events = _test_events(
        'pm.test("checks", function () {',
        "  pm.expect(pm.response.responseTime).to.be.below(800);",
        '  pm.response.to.have.header("Content-Type");',
        '  pm.expect(jsonData.role).to.eql("admin");',
        "});",
    )
    result = _extract_assertions(events)
    assert Assertion(kind="response_time_below", value=800) in result
    assert Assertion(kind="header_present", target="Content-Type") in result
    assert Assertion(kind="json_field_equals", target="role", value="admin") in result
    assert len(result) == 3


def test_unrecognised_pattern_is_skipped():
    events = _test_events(
        'pm.test("custom", function () {',
        "  pm.expect(jsonData.items.length).to.be.greaterThan(0);",
        "  doSomethingCustom();",
        "});",
    )
    assert _extract_assertions(events) == []


def test_json_field_with_unparseable_value_is_skipped():
    events = _test_events("pm.expect(jsonData.name).to.eql(someVariable);")
    assert _extract_assertions(events) == []


def test_non_test_events_are_ignored():
    events = [{"listen": "prerequest", "script": {"exec": ['pm.response.to.have.header("X");']}}]
    assert _extract_assertions(events) == []


def test_status_assertion_is_not_duplicated_here():
    # Status is handled by expected_status, not by _extract_assertions.
    events = _test_events("pm.response.to.have.status(201);")
    assert _extract_assertions(events) == []


# --- Assertion.to_pytest rendering ---------------------------------------


def test_to_pytest_response_time():
    line = Assertion(kind="response_time_below", value=500).to_pytest()
    assert line == (
        'assert response.elapsed.total_seconds() * 1000 < 500, "response time exceeded 500 ms"'
    )


def test_to_pytest_header_present():
    line = Assertion(kind="header_present", target="Content-Type").to_pytest()
    assert line == ("assert 'Content-Type' in response.headers, \"missing header Content-Type\"")


def test_to_pytest_json_field_string():
    line = Assertion(kind="json_field_equals", target="name", value="John").to_pytest()
    assert line == ("assert response.json().get('name') == 'John', \"json field name mismatch\"")


def test_to_pytest_json_field_number():
    line = Assertion(kind="json_field_equals", target="id", value=42).to_pytest()
    assert line == ("assert response.json().get('id') == 42, \"json field id mismatch\"")


# --- integration: parse_collection populates assertions ------------------


def test_parse_collection_populates_assertions(tmp_path: Path):
    collection = tmp_path / "c.json"
    collection.write_text(
        """
        {
          "info": {"schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [
            {
              "name": "Get user",
              "request": {"method": "GET", "url": {"raw": "{{base}}/user"}},
              "event": [
                {"listen": "test", "script": {"exec": [
                  "pm.response.to.have.status(200);",
                  "pm.expect(pm.response.responseTime).to.be.below(500);",
                  "pm.response.to.have.header(\\"Content-Type\\");",
                  "pm.expect(pm.response.json().name).to.eql(\\"Ada\\");"
                ]}}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    requests = parse_collection(collection)
    assert len(requests) == 1
    req = requests[0]
    assert req.expected_status == 200
    assert Assertion(kind="response_time_below", value=500) in req.assertions
    assert Assertion(kind="header_present", target="Content-Type") in req.assertions
    assert Assertion(kind="json_field_equals", target="name", value="Ada") in req.assertions


# --- integration: generated file carries the assertions ------------------


def test_generate_emits_translated_assertions(tmp_path: Path):
    from core.generator import generate
    from core.parser import ParsedRequest

    req = ParsedRequest(
        name="Get user",
        method="GET",
        url="https://api.example.com/user",
        headers={},
        body=None,
        expected_status=200,
        assertions=[
            Assertion(kind="response_time_below", value=500),
            Assertion(kind="header_present", target="Content-Type"),
            Assertion(kind="json_field_equals", target="name", value="Ada"),
        ],
        folder=None,
    )
    out = tmp_path / "test_out.py"
    generate([req], "demo", out)
    content = out.read_text(encoding="utf-8")

    assert "assert response.elapsed.total_seconds() * 1000 < 500" in content
    assert "assert 'Content-Type' in response.headers" in content
    assert "assert response.json().get('name') == 'Ada'" in content
    # the generated module must be valid, importable Python
    compile(content, str(out), "exec")
