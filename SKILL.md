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

## When to invoke

Trigger this skill if any of these conditions hold:

- The user mentions a Postman collection, a `.postman_collection.json` file, a Postman v2.1 export, or a Newman setup.
- The user wants pytest tests generated from an API definition they already have.
- The user is migrating an API regression suite from Postman/Newman to Python.
- The user wants their existing Postman documentation to drive CI without rewriting tests by hand.

Do not invoke this skill for OpenAPI specs, HAR files, Insomnia exports, or raw cURL transcripts. Those are different input formats and not supported.

## Quick start

1. Install the CLI from PyPI:
   ```bash
   pip install postman2pytest
   ```
2. Run the converter against the collection file:
   ```bash
   postman2pytest --collection my_api.postman_collection.json --out tests/test_api.py
   ```
3. Set the base URL the suite should hit (the generated tests read it from the environment, not from the collection's stored `host`):
   ```bash
   export BASE_URL=https://api.example.com
   ```
4. Run the suite:
   ```bash
   pytest tests/test_api.py -v
   ```
5. Commit the generated module into the repo. Re-run step 2 whenever the collection changes.

## Inputs and outputs

**Input:** a Postman Collection v2.1 JSON file. Older v1 collections are not supported; convert them in the Postman desktop app first.

**Output:** a single pytest module. One test function per request in the collection. Folder hierarchy is preserved in test names via underscores. Headers, query params, JSON request body, and basic auth header are emitted verbatim. The HTTP status code is asserted against the example saved in the collection.

**Filtering:** pass `--filter-folder NAME` to generate tests only for one Postman folder. Useful for splitting a large collection across multiple suites.

**Auth scrubbing:** `Authorization` and other header names that look like credentials are read from environment variables in the generated test, never from the collection. The collection's stored value is replaced with an env-var lookup.

## What it does not do (call out before suggesting)

- **OAuth flows.** Token refresh is not generated. Set the token in the env var externally.
- **Pre-request scripts.** Postman's JavaScript pre-request scripts are not translated; the generated code is plain Python.
- **Response-body assertions.** Only the status code is asserted by default. Body assertions live on the v1.1 roadmap.
- **Environments file.** The Postman environment file is not consumed; the generated suite reads `BASE_URL` and credential env vars only.

If a user needs any of the above, say so honestly and link to the open issue rather than promising a workaround.

## Example walkthrough

A 12-request Postman collection with three folders (`Users`, `Orders`, `Admin`) produces:

- One pytest module of about 200 lines.
- 12 test functions named like `test_users_get_user_by_id`, `test_orders_create_order`.
- Skipped tests for requests with no saved example response (the collection lacks the expected status to assert against).
- A `conftest.py`-free design: the module is self-contained, requires only `requests` and `pytest` at runtime.

Run the suite, see the green dots, commit the file. The collection-to-tests round trip is the unit of work.

## Limitations and known gaps

See open issues on the repo for current roadmap. The most-requested missing features are tracked there with `enhancement` labels.

## References

- Project README and full design write-up: https://github.com/golikovichev/postman2pytest
- Article explaining the bridge concept: https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn
