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

Read a Postman Collection v2.1 JSON file, write a single pytest module that replays every request and asserts on the response.

The collection stays the source of truth. The generated suite is committable code: no Newman runtime, no Postman license, no JavaScript pre-request scripts. Re-run the converter when the collection changes; the file regenerates cleanly.

## Quick start

1. Install the CLI from PyPI:
   ```bash
   pip install postman2pytest
   ```
2. Verify the collection is Postman v2.1. Open the JSON file and check `"info" → "schema"` contains `v2.1.0`. Older v1 collections must be re-exported from the Postman desktop app first.
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

**Input:** a Postman Collection v2.1 JSON file. Older v1 collections are not supported; convert them in the Postman desktop app first.

**Output:** a single pytest module. One test function per request in the collection. Folder hierarchy is preserved in test names via underscores. Headers, query params, JSON request body, and basic auth header are emitted verbatim. The HTTP status code is asserted against the example saved in the collection.

**Filtering:** pass `--filter-folder NAME` to generate tests only for one Postman folder. Useful for splitting a large collection across multiple suites.

**Auth scrubbing:** `Authorization` and other header names that look like credentials are read from environment variables in the generated test, never from the collection. The collection's stored value is replaced with an env-var lookup.

## Example walkthrough

Bundled `data/sample_collection.json` (Sample API: one folder `Users` with two requests plus a top-level `Health check`).

```text
$ postman2pytest --collection data/sample_collection.json --out /tmp/test_all.py
INFO: Parsed 3 requests from collection
INFO: Written 3 tests to /tmp/test_all.py

Generated 3 test(s) -> /tmp/test_all.py
  Run with: pytest /tmp/test_all.py -v
  Tip: set BASE_URL env var to point at your API
```

The generated file contains three test functions:

```python
def test_users_get_get_all_users():
def test_users_post_create_user():
def test_get_health_check():
```

Filtering to a single folder shrinks the output:

```text
$ postman2pytest --collection data/sample_collection.json --out /tmp/test_users.py --filter-folder Users
INFO: Parsed 3 requests from collection
INFO: Written 2 tests to /tmp/test_users.py

Generated 2 test(s) -> /tmp/test_users.py
```

Folder matching is case-insensitive: `Users`, `users`, and `USERS` all select the same folder.

The generated module is self-contained. It imports `os`, `pytest`, and `requests`; nothing else. No `conftest.py` is required.

## Limitations and known gaps

- **OAuth flows.** Token refresh is not generated. Set the token in the env var named by the collection's `Authorization` header (the generated test reads it via `os.environ.get("token", "")` or the header-name equivalent).
- **Pre-request scripts.** Postman's JavaScript pre-request scripts are not translated. If the original request depended on a script to compute a header or signature, the generated test will send the literal placeholder and fail at runtime; rewrite that piece in Python before running.
- **Response-body assertions.** Only the HTTP status code is asserted. Body content is not validated; if a request returns 200 with a wrong payload, the generated test passes anyway.
- **Environments file.** Postman environment exports (`*.postman_environment.json`) are not consumed. The generated suite reads `BASE_URL` and credential env vars only.

## References

- Project README and full design write-up: https://github.com/golikovichev/postman2pytest
- Article explaining the bridge concept: https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn
