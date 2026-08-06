"""CLI-level tests for collection variables reaching the generated tests.

The unit tests in test_environment.py cover the parsing and layering rules.
These check the wiring: a value declared in the collection's own `variable`
block has to survive all the way into the generated file, and an environment
file passed with --env has to win over it.
"""

import json
import sys
from pathlib import Path

import main as cli


def _collection() -> dict:
    return {
        "info": {"name": "C", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/"},
        "variable": [{"key": "baseUrl", "value": "https://api.example.com"}],
        "item": [
            {
                "name": "list users",
                "request": {"method": "GET", "url": {"raw": "{{baseUrl}}/users"}},
            }
        ],
    }


def _run(monkeypatch, tmp_path: Path, *extra: str) -> str:
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(_collection()), encoding="utf-8")
    out = tmp_path / "test_gen.py"
    argv = ["main.py", "--collection", str(cpath), "--out", str(out), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    return out.read_text(encoding="utf-8")


def test_collection_variable_is_inlined_without_an_environment_file(monkeypatch, tmp_path: Path):
    text = _run(monkeypatch, tmp_path)
    assert "https://api.example.com" in text
    assert "os.environ.get('baseUrl'" not in text
    compile(text, "gen", "exec")


def test_environment_file_wins_but_does_not_erase_the_other_collection_variables(
    monkeypatch, tmp_path: Path
):
    # Both layering directions in one run: the file overrides the name it
    # declares, and the name it says nothing about still comes from the
    # collection rather than falling through to a lookup.
    collection = _collection()
    collection["variable"].append({"key": "apiVersion", "value": "v2"})
    collection["item"][0]["request"]["url"]["raw"] = "{{baseUrl}}/{{apiVersion}}/users"
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(collection), encoding="utf-8")
    epath = tmp_path / "e.json"
    epath.write_text(
        json.dumps({"values": [{"key": "baseUrl", "value": "https://staging.example.com"}]}),
        encoding="utf-8",
    )
    out = tmp_path / "test_gen.py"
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--collection", str(cpath), "--out", str(out), "--env", str(epath)],
    )
    assert cli.main() == 0
    text = out.read_text(encoding="utf-8")
    assert 'BASE_URL = os.environ.get("BASE_URL", "https://staging.example.com")' in text
    assert 'url = f"{BASE_URL}/v2/users"' in text  # apiVersion still from the collection
    assert "https://api.example.com" not in text
    compile(text, "gen", "exec")


def test_secret_collection_variable_stays_out_of_the_generated_code(monkeypatch, tmp_path: Path):
    cpath = tmp_path / "c.json"
    collection = _collection()
    collection["variable"].append({"key": "apiKey", "value": "s3cr3t", "type": "secret"})
    collection["item"][0]["request"]["header"] = [{"key": "X-Key", "value": "{{apiKey}}"}]
    cpath.write_text(json.dumps(collection), encoding="utf-8")
    out = tmp_path / "test_gen.py"
    monkeypatch.setattr(sys, "argv", ["main.py", "--collection", str(cpath), "--out", str(out)])
    assert cli.main() == 0
    text = out.read_text(encoding="utf-8")
    assert "s3cr3t" not in text
    compile(text, "gen", "exec")


def test_collection_without_variables_keeps_the_previous_output_shape(monkeypatch, tmp_path: Path):
    # A collection that declares nothing must generate exactly what it did
    # before this feature existed: plain os.environ lookups, no fixtures. An
    # empty variable block should not switch the generator into fixture mode.
    collection = _collection()
    del collection["variable"]
    collection["item"][0]["request"]["url"]["raw"] = "{{baseUrl}}/users/{{userId}}"
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(collection), encoding="utf-8")
    out = tmp_path / "test_gen.py"
    monkeypatch.setattr(sys, "argv", ["main.py", "--collection", str(cpath), "--out", str(out)])
    assert cli.main() == 0
    text = out.read_text(encoding="utf-8")
    assert "os.environ.get('userId', '')" in text
    assert "@pytest.fixture" not in text
    compile(text, "gen", "exec")


def test_collection_base_url_becomes_the_BASE_URL_default(monkeypatch, tmp_path: Path):
    # The leading URL variable maps to BASE_URL, so its value belongs in the
    # BASE_URL default rather than baked into every request. Inlining it there
    # would hardcode the address and silently break `BASE_URL=... pytest`,
    # which the CLI itself suggests.
    text = _run(monkeypatch, tmp_path)
    assert 'BASE_URL = os.environ.get("BASE_URL", "https://api.example.com")' in text
    assert 'url = f"{BASE_URL}/users"' in text
    compile(text, "gen", "exec")


def _generate(monkeypatch, tmp_path: Path, collection: dict, *extra: str) -> str:
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps(collection), encoding="utf-8")
    out = tmp_path / "test_gen.py"
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--collection", str(cpath), "--out", str(out), *extra]
    )
    assert cli.main() == 0
    text = out.read_text(encoding="utf-8")
    compile(text, "gen", "exec")
    return text


def test_a_second_host_variable_is_not_collapsed_into_BASE_URL(monkeypatch, tmp_path: Path):
    # Only one variable can be BASE_URL. A request leading with a different
    # host must keep that host, not silently retarget to the first one.
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "variable": [
            {"key": "apiHost", "value": "https://api.example.com"},
            {"key": "authHost", "value": "https://auth.example.com"},
        ],
        "item": [
            {"name": "list", "request": {"method": "GET", "url": {"raw": "{{apiHost}}/users"}}},
            {
                "name": "token",
                "request": {"method": "POST", "url": {"raw": "{{authHost}}/oauth/token"}},
            },
        ],
    }
    text = _generate(monkeypatch, tmp_path, collection)
    assert 'BASE_URL = os.environ.get("BASE_URL", "https://api.example.com")' in text
    assert 'url = f"{BASE_URL}/users"' in text
    assert 'url = "https://auth.example.com/oauth/token"' in text


def test_a_leading_variable_that_is_not_a_host_stays_in_the_path(monkeypatch, tmp_path: Path):
    # A tenant slug at the front of the path is not a base URL. Treating it as
    # one would both drop the segment and leave BASE_URL unusable.
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "variable": [{"key": "tenant", "value": "acme"}],
        "item": [
            {"name": "things", "request": {"method": "GET", "url": {"raw": "{{tenant}}/things"}}}
        ],
    }
    text = _generate(monkeypatch, tmp_path, collection)
    assert 'BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")' in text
    assert 'url = f"{BASE_URL}/acme/things"' in text


def test_a_non_host_leading_variable_from_the_environment_file_also_stays(
    monkeypatch, tmp_path: Path
):
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "item": [
            {"name": "things", "request": {"method": "GET", "url": {"raw": "{{tenant}}/things"}}}
        ],
    }
    epath = tmp_path / "e.json"
    epath.write_text(json.dumps({"values": [{"key": "tenant", "value": "acme"}]}), encoding="utf-8")
    text = _generate(monkeypatch, tmp_path, collection, "--env", str(epath))
    assert 'url = f"{BASE_URL}/acme/things"' in text


def test_a_url_that_is_only_the_base_variable_gains_no_trailing_slash(monkeypatch, tmp_path: Path):
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "variable": [{"key": "baseUrl", "value": "https://only.example.com"}],
        "item": [{"name": "root", "request": {"method": "GET", "url": {"raw": "{{baseUrl}}"}}}],
    }
    text = _generate(monkeypatch, tmp_path, collection)
    assert 'url = f"{BASE_URL}"' in text


def test_a_host_and_port_pair_is_not_split_by_BASE_URL(monkeypatch, tmp_path: Path):
    # {{host}}:{{port}} is one address written in two variables. Only a
    # variable followed by a path separator (or ending the URL) is the base;
    # anything else is inlined, or the port lands in the path.
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "variable": [
            {"key": "host", "value": "http://localhost"},
            {"key": "port", "value": "8080"},
        ],
        "item": [
            {"name": "u", "request": {"method": "GET", "url": {"raw": "{{host}}:{{port}}/api"}}}
        ],
    }
    text = _generate(monkeypatch, tmp_path, collection)
    assert 'url = "http://localhost:8080/api"' in text
    assert ":8080" not in text.split("url = ")[1].split("\n")[0].replace(
        "http://localhost:8080/api", ""
    )


def test_a_base_variable_followed_by_a_query_string_keeps_its_own_shape(
    monkeypatch, tmp_path: Path
):
    collection = {
        "info": {"name": "C", "schema": "v2.1.0"},
        "variable": [{"key": "baseUrl", "value": "https://api.example.com/v1"}],
        "item": [{"name": "q", "request": {"method": "GET", "url": {"raw": "{{baseUrl}}?q=1"}}}],
    }
    text = _generate(monkeypatch, tmp_path, collection)
    assert 'url = "https://api.example.com/v1?q=1"' in text
