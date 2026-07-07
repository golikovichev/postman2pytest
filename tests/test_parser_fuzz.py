"""Fuzz / property-based tests for the Postman collection parser.

These feed arbitrary and deliberately malformed input to ``parse_collection``
and assert it fails gracefully: it either returns a list of parsed requests or
raises a clear ``ValueError``. It must never crash with an unhandled
``AttributeError``, ``TypeError`` or ``RecursionError``, which is what a user
would otherwise see when handed a corrupt or non-standard JSON file.

Regression guards for the malformed-input classes found by fuzzing:
non-object root, non-object ``info``, non-list ``item``, scalar items, and
folder trees nested deeply enough to overflow the stack.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from core.parser import parse_collection

# Quiet the per-skip warnings the parser emits on malformed input; we assert on
# behaviour (return value or exception type), not on log noise.
logging.getLogger("core.parser").setLevel(logging.CRITICAL)

# Any JSON-serialisable value: scalars at the leaves, lists and string-keyed
# dicts as containers. This covers both well-shaped and malformed collections.
json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=30,
)


def _parse(value: object) -> list:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(json.dumps(value))
        path = Path(tmp.name)
    try:
        return parse_collection(path)
    finally:
        path.unlink(missing_ok=True)


@given(value=json_values)
@settings(max_examples=300, deadline=None)
def test_parser_is_graceful_on_arbitrary_json(value: object) -> None:
    """Any JSON value parses to a list or raises a clear ValueError, never a crash."""
    try:
        result = _parse(value)
    except ValueError:
        return  # the one deliberate, documented failure mode
    assert isinstance(result, list)


# Collection-shaped fuzzing: keep the v2.1 envelope and fuzz the parts the
# request path reads, so generation reaches deeper into the parser.
def _collection_shaped() -> st.SearchStrategy:
    request = st.fixed_dictionaries(
        {
            "method": st.text() | st.integers() | st.none(),
            "url": st.text() | st.fixed_dictionaries({"raw": st.text()}) | st.none(),
            "header": st.lists(st.dictionaries(st.text(), st.text(), max_size=3), max_size=3)
            | st.none(),
            "body": st.none() | st.fixed_dictionaries({"mode": st.text(), "raw": st.text()}),
        }
    )
    item = st.fixed_dictionaries({"name": st.text(), "request": request}) | st.none() | st.text()
    return st.fixed_dictionaries(
        {
            "info": st.fixed_dictionaries({"schema": st.just("v2.1")}),
            "item": st.lists(item, max_size=6),
        }
    )


@given(collection=_collection_shaped())
@settings(max_examples=200, deadline=None)
def test_parser_is_graceful_on_collection_shaped_input(collection: dict) -> None:
    try:
        result = _parse(collection)
    except ValueError:
        return
    assert isinstance(result, list)


# --- targeted regression guards for the specific crash classes found ---


def test_non_object_root_raises_value_error() -> None:
    for value in ([], "x", 42, None):
        try:
            _parse(value)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for root {value!r}")


def test_non_object_info_is_tolerated() -> None:
    assert _parse({"info": "not-a-dict", "item": []}) == []


def test_non_list_item_is_tolerated() -> None:
    assert _parse({"item": "not-a-list"}) == []


def test_scalar_items_are_skipped() -> None:
    assert _parse({"item": [123, None, "str"]}) == []


def test_deeply_nested_folders_raise_value_error() -> None:
    raw = "{" + '"item":[{"name":"f","item":' * 2000 + "[]" + "}]" * 2000 + "}"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(raw)
        path = Path(tmp.name)
    try:
        parse_collection(path)
    except ValueError:
        return
    finally:
        path.unlink(missing_ok=True)
    raise AssertionError("expected ValueError for deeply nested folders")
