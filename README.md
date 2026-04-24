# postman2pytest

[![CI](https://github.com/golikovichev/postman2pytest/actions/workflows/ci.yml/badge.svg)](https://github.com/golikovichev/postman2pytest/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/postman2pytest)](https://pypi.org/project/postman2pytest/)
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](https://pypi.org/project/postman2pytest/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Convert a **Postman Collection v2.1** JSON file into a ready-to-run **pytest** test suite — in one command.

```bash
postman2pytest --collection my_api.json --out tests/test_api.py
BASE_URL=https://api.example.com pytest tests/test_api.py -v
```

## Why

Postman collections document your API. `postman2pytest` turns that documentation into executable regression tests that run in CI — no manual rewriting, no drift.

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

## How It Works

1. **Parse** — reads the Postman Collection JSON, flattens nested folders into a flat request list
2. **Extract** — captures method, URL, headers, body, and expected status from `pm.response.to.have.status()` test scripts
3. **Generate** — renders a Jinja2 template into a `.py` file with one `def test_*()` per request

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
- ✅ Malformed items skipped with a warning — rest of collection still generated

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
