---
name: postman2pytest
description: Convert a Postman Collection v2.1 JSON file into a runnable pytest test suite using the postman2pytest CLI. Use when the user has a Postman collection (a .postman_collection.json or v2.1 JSON export) and wants to run it as pytest in CI, when migrating from Postman/Newman to a Python-native test stack, when bridging Postman-documented APIs into a pytest-based regression suite, when the user asks to generate pytest tests from Postman, or when the user mentions wanting to keep Postman as the source of truth but run the suite with pytest.
license: MIT
metadata:
  category: "api-testing"
  homepage: "https://github.com/golikovichev/postman2pytest"
  pypi: "https://pypi.org/project/postman2pytest/"
  version: "1.0.2"
---

# postman2pytest

Read a Postman Collection v2.1 JSON file, write a single pytest module that replays every request and asserts on the response. The collection stays the source of truth; the generated suite is committable code. Re-run the converter when the collection changes.

Full CLI reference, auth scrubbing details, stress testing, CI workflow templates, and limitations live in `REFERENCE.md` next to this file.

## Quick start

1. Install the CLI from PyPI:
   ```bash
   pip install postman2pytest
   ```
2. Verify the collection is Postman v2.1. Open the JSON and check `"info" → "schema"` contains `v2.1.0`.
3. Run the converter:
   ```bash
   postman2pytest --collection my_api.postman_collection.json --out tests/test_api.py
   ```
4. Sanity-check the output (test count matches the collection's request count):
   ```bash
   grep -c '^def test_' tests/test_api.py
   ```
5. Set the base URL and any credential env vars the suite reads:
   ```bash
   export BASE_URL=https://api.example.com
   export AUTHORIZATION="Bearer ..."
   ```
6. Run the suite:
   ```bash
   pytest tests/test_api.py -v
   ```
7. Commit the generated module. Re-run step 3 whenever the collection changes.

## Example

A collection with one folder `Users` (two requests) and a top-level `Health check` request produces three test functions:

```python
def test_users_get_get_all_users():
def test_users_post_create_user():
def test_get_health_check():
```

Filtering to a single folder shrinks the output to just the two `Users` tests:

```bash
postman2pytest --collection my_api.postman_collection.json \
    --out /tmp/test_users.py --filter-folder Users
```

Folder matching is case-insensitive. The generated module is self-contained: imports `os`, `pytest`, and `requests`; nothing else, no `conftest.py` required.

## Common errors

- **Schema mismatch:** re-export the collection as v2.1 in Postman.
- **`BASE_URL not set`:** the generated module reads it from the environment, not the collection's stored host.
- **File too large:** pass `--max-input-mb` higher, or split via `--filter-folder`.

Full error-handling tree + CLI flag reference + auth scrubbing details in `REFERENCE.md`.

## CI

For GitHub Actions / GitLab CI / Jenkins templates and a stress-test workflow on 500-2000 request collections, see `REFERENCE.md` sections "CI integration" and "Testing at scale".

## References

- Bundle: `REFERENCE.md` (CLI flags, validation, stress testing, error tree, CI templates)
- Project: https://github.com/golikovichev/postman2pytest
- PyPI: https://pypi.org/project/postman2pytest/
- Article: https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn
