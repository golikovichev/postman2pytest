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

## Quick start

1. Install the CLI from PyPI:
   ```bash
   pip install postman2pytest
   ```
2. Verify the collection is Postman v2.1. Open the JSON file and check `"info" → "schema"` contains `v2.1.0`.
3. Run the converter against the collection file:
   ```bash
   postman2pytest --collection my_api.postman_collection.json --out tests/test_api.py
   ```
4. Set the base URL the suite should hit (the generated tests read it from the environment, not from the collection's stored `host`):
   ```bash
   export BASE_URL=https://api.example.com
   ```
5. Run the suite:
   ```bash
   pytest tests/test_api.py -v
   ```
6. Commit the generated module into the repo. Re-run step 3 whenever the collection changes.

### Error handling

- **Schema mismatch:** the converter exits non-zero with a clear message naming the unsupported schema. Re-export the collection as v2.1 in Postman.
- **File too large:** `--max-input-mb` (default 100) refuses collections above the limit. Pass a larger value if the collection is genuinely that big, or split it via `--filter-folder`.
- **Pytest failures on first run:** check `BASE_URL` is set and reachable. The generated module assumes the API is live; it does not mock responses.

## Inputs and outputs

**Output:** a single pytest module. One test function per request in the collection. Folder hierarchy is preserved in test names via underscores. Headers, query params, JSON request body, and basic auth header are emitted verbatim. The HTTP status code is asserted against the example saved in the collection.

**Filtering:** pass `--filter-folder NAME` to generate tests only for one Postman folder. Useful for splitting a large collection across multiple suites.

**Auth scrubbing:** `Authorization` and other header names that look like credentials are read from environment variables in the generated test, never from the collection. The collection's stored value is replaced with an env-var lookup.

## Example walkthrough

A collection with one folder `Users` (two requests) and a top-level `Health check` request produces three test functions:

```python
def test_users_get_get_all_users():
def test_users_post_create_user():
def test_get_health_check():
```

Filtering to a single folder shrinks the output to just the two `Users` tests:

```bash
postman2pytest --collection my_api.postman_collection.json --out /tmp/test_users.py --filter-folder Users
```

Folder matching is case-insensitive: `Users`, `users`, and `USERS` all select the same folder.

The generated module is self-contained. It imports `os`, `pytest`, and `requests`; nothing else. No `conftest.py` is required.

## Limitations and known gaps

- **OAuth flows:** Token refresh is not generated. Set the token in the env var named by the collection's `Authorization` header.
- **Pre-request scripts:** Postman's JavaScript pre-request scripts are not translated. Rewrite any script-computed headers or signatures in Python before running.
- **Response-body assertions:** Only the HTTP status code is asserted. Body content is not validated.
- **Environments file:** Postman environment exports (`*.postman_environment.json`) are not consumed. The generated suite reads `BASE_URL` and credential env vars only.

## References

- Project README and full design write-up: https://github.com/golikovichev/postman2pytest
- Article explaining the bridge concept: https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn
