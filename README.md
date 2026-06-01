# postman2pytest

[![CI](https://github.com/golikovichev/postman2pytest/actions/workflows/ci.yml/badge.svg)](https://github.com/golikovichev/postman2pytest/actions/workflows/ci.yml)
[![CodeQL](https://github.com/golikovichev/postman2pytest/actions/workflows/codeql.yml/badge.svg)](https://github.com/golikovichev/postman2pytest/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/gh/golikovichev/postman2pytest/branch/main/graph/badge.svg)](https://codecov.io/gh/golikovichev/postman2pytest)
[![PyPI](https://img.shields.io/pypi/v/postman2pytest)](https://pypi.org/project/postman2pytest/)
[![Downloads](https://static.pepy.tech/badge/postman2pytest/month)](https://pepy.tech/project/postman2pytest)
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13-blue)](https://pypi.org/project/postman2pytest/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/golikovichev/postman2pytest)](https://github.com/golikovichev/postman2pytest/commits/main)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13008/badge)](https://www.bestpractices.dev/projects/13008)

Convert a **Postman Collection v2.1** JSON file into a ready-to-run **pytest** test suite. One command.

📖 **[Read the article on Dev.to](https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn)**

```bash
postman2pytest --collection my_api.json --out tests/test_api.py
BASE_URL=https://api.example.com pytest tests/test_api.py -v
```

## Why

Postman collections document your API. `postman2pytest` turns that documentation into executable regression tests that run in CI. No manual rewriting, no drift.

## Install

```bash
pip install postman2pytest
```

Or from source:

```bash
git clone https://github.com/golikovichev/postman2pytest
cd postman2pytest
pip install -e .
```

## Usage

```bash
postman2pytest \
  --collection data/my_api.postman_collection.json \
  --out generated_tests/test_api.py
```

Then run the generated tests:

```bash
BASE_URL=https://staging.example.com pytest generated_tests/test_api.py -v
```

### Options

| Flag | Required | Description |
|------|----------|-------------|
| `--collection` | ✅ | Path to Postman Collection v2.1 JSON |
| `--out` | ✅ | Output path for generated pytest file |
| `--base-url` | ❌ | Tip printed after generation (does not override env var) |
| `--filter-folder` | ❌ | Generate tests only for the named Postman folder |

To regenerate tests for one folder, pass its Postman folder name:

```bash
postman2pytest \
  --collection data/my_api.postman_collection.json \
  --out generated_tests/test_users.py \
  --filter-folder Users
```

## Examples

### Generate tests for a single folder

The bundled `data/sample_collection.json` file includes a `Users` folder and one top-level `Health check` request. Generating from the whole collection creates three tests:

```bash
postman2pytest \
  --collection data/sample_collection.json \
  --out /tmp/test_all.py
```

```text
Generated 3 test(s) -> /tmp/test_all.py
```

The generated file contains tests with folder-prefixed names:

```python
def test_users_get_get_all_users():
def test_users_post_create_user():
def test_get_health_check():
```

To generate only the requests from the `Users` folder, pass `--filter-folder`. Folder matching is case-insensitive, so `Users`, `users`, and `USERS` all match the same folder:

```bash
postman2pytest \
  --collection data/sample_collection.json \
  --out /tmp/test_users.py \
  --filter-folder Users
```

```text
Generated 2 test(s) -> /tmp/test_users.py
```

The filtered output contains only the tests from that folder:

```python
def test_users_get_get_all_users():
def test_users_post_create_user():
```

## How It Works

1. **Parse**: reads the Postman Collection JSON, flattens nested folders into a flat request list
2. **Extract**: captures method, URL, headers, body, and expected status from `pm.response.to.have.status()` test scripts
3. **Generate**: renders a Jinja2 template into a `.py` file with one `def test_*()` per request

### Variable substitution

Postman variables `{{base_url}}` become `ENV_base_url` in the URL, resolved at runtime via the `BASE_URL` environment variable.

## Generated output example

Given a Postman request `GET {{base_url}}/api/v1/users` with a test asserting status 200, the output is:

```python
def test_get_users():
    """GET ENV_base_url/api/v1/users"""
    url = f"{BASE_URL}/api/v1/users"
    headers = {}
    response = requests.get(url, headers=headers)
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
```

## Supported features

- ✅ Postman Collection v2.1 (v2.0 accepted with a warning)
- ✅ Nested folders → flattened with folder prefix in test name
- ✅ GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS
- ✅ Request headers (disabled headers excluded)
- ✅ Raw JSON body
- ✅ Expected status from `pm.response.to.have.status(N)` test scripts
- ✅ Falls back to 200 when no status assertion found
- ✅ Malformed items skipped with a warning. Rest of collection still generated

## Limitations

Honest scope so you know what to expect before pointing the tool at a real
collection.

- ❌ **Postman environments are not read.** `{{baseUrl}}` and friends are
  passed through verbatim into the generated `url` strings. Set the
  `BASE_URL` env var at test time, or post-process the file to swap in the
  values you care about.
- ❌ **Pre-request scripts are skipped.** Auth that depends on `pm.sendRequest`
  to grab a token before each call (e.g. OAuth client-credentials flows
  refreshing per request) needs manual translation into a pytest fixture.
- ❌ **Test scripts beyond a status assertion are dropped.** Only
  `pm.response.to.have.status(N)` is extracted; chai-style body shape checks,
  custom JS, and `pm.variables.set(...)` calls do not survive the conversion.
- ❌ **Form-data and `urlencoded` bodies are not generated yet.** Only raw
  JSON bodies are written into the test file. Multipart uploads, file
  attachments, and form fields are recognised by the parser but left out of
  the rendered request call. Tracked in
  [issue #1](https://github.com/golikovichev/postman2pytest/issues/1).
- ❌ **Cookies, certificates, and per-request proxy settings are ignored.**
- ⚠ **Variable substitution is shallow.** Path variables (`/users/:id`)
  become `{id}` placeholders; collection-level variables are not resolved.
- ⚠ **Generated `BASE_URL` defaults to an empty string.** Tests that hit a
  full URL in the Postman item still resolve, but bare path items will fail
  until the env var is set.

If a missing feature is blocking you, please open an issue with a redacted
slice of the collection that demonstrates it.

## Roadmap

Short list of what is next, roughly in priority order. Tracked in detail on
the [issues board](https://github.com/golikovichev/postman2pytest/issues).

- **Form-data and `urlencoded` body support**: currently parsed but not
  rendered. Blocking most file-upload and OAuth-token-endpoint test cases.
  ([#1](https://github.com/golikovichev/postman2pytest/issues/1))
- **Pre-request script translation, scoped scope**: surface the script,
  even as a `pytest.fixture` stub, so the operator does not lose the auth
  context silently.
- **`--ai-edges` mode**: opt-in pass that asks an LLM to fill in edge
  cases (boundary numbers, missing required fields, type-confusion payloads)
  on top of the deterministic happy-path tests.
  ([#2](https://github.com/golikovichev/postman2pytest/issues/2))
- **Environment file ingestion**: accept Postman environment JSON exports
  and write a matching `conftest.py` so `{{baseUrl}}` and similar resolve
  through pytest variables.
- **Allure step annotations toggle**: `--allure` flag that wraps each
  generated test in `allure.step(...)` blocks so the report shows the
  Postman folder structure.

Contributions to any of the above are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Related projects and patterns

Once `postman2pytest` has generated your suite, the next questions are
usually «how do I structure fixtures across all these requests» and
«how do I run them under async with shared auth state». The
[tessl-labs/pytest-api-testing](https://tessl.io/registry/tessl-labs/pytest-api-testing)
skill on the Tessl Registry collects the conventions that worked for
that follow-on layer: httpx `AsyncClient` setup, `conftest.py` fixture
shape, database isolation, parametrize patterns for edge cases, and
auth-flow handling. Useful reference if your generated tests grow
beyond the request-by-request shape this tool emits.

Sister projects in the same workspace:

- [secure-log2test](https://github.com/golikovichev/secure-log2test): same idea but the input is Kibana / Elasticsearch JSON logs instead of Postman collections.
- [pytest-conversational](https://github.com/golikovichev/pytest-conversational): pytest plugin for multi-turn dialogue testing.
- [phoenix2pytest](https://github.com/golikovichev/phoenix2pytest): same idea but the input is labeled LLM failure traces from Arize Phoenix instead of Postman collections.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

MIT. See [LICENSE](LICENSE).
