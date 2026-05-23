# postman2pytest reference

Detailed inputs, outputs, CLI flags, filters, auth scrubbing, limitations, and testing-at-scale notes. SKILL.md keeps the quick-start and one example. Read this file when you need the full surface.

## Inputs and outputs

**Input:** a Postman Collection v2.1 JSON export. The collection schema must include `"info" → "schema"` ending in `v2.1.0`. Older schemas (v2.0, v1.0) are not converted; re-export the collection from current Postman to upgrade.

**Output:** a single pytest module. One test function per request in the collection. Folder hierarchy is preserved in test names via underscores. Headers, query params, JSON request body, and basic auth header are emitted verbatim. The HTTP status code is asserted against the example saved in the collection.

**Auth scrubbing:** `Authorization` and other header names that look like credentials are read from environment variables in the generated test, never from the collection. The collection's stored value is replaced with an env-var lookup like `os.environ["AUTHORIZATION"]`.

## CLI flags

| Flag | Default | Purpose |
| --- | --- | --- |
| `--collection PATH` | required | Postman Collection v2.1 JSON file. |
| `--out PATH` | required | Output `.py` file path. Parent directory must exist. |
| `--filter-folder NAME` | none | Generate tests only for one Postman folder. Case-insensitive match. Useful for splitting large collections across multiple pytest modules. |
| `--max-input-mb N` | 100 | Refuse collections above this size in MB. Pass a larger value if the collection is genuinely that big, or split via `--filter-folder`. |
| `--help` | - | Full CLI reference. |
| `--version` | - | Print installed version. |

## Validation after generation

After running the converter, sanity-check the output before committing:

```bash
# Count generated test functions
grep -c '^def test_' tests/test_api.py
# Confirm collection request count matches (folder filters apply if used)
python -c "import json; c=json.load(open('my_api.postman_collection.json')); print(sum(1 for _ in c.get('item', [])))"
# Lint the generated module
python -m py_compile tests/test_api.py
```

If the test count looks wrong, re-run with `--filter-folder` to isolate which folder over-generated, or check the collection for nested `item` arrays that the converter walks.

## Testing at scale

The repo ships `scripts/generate_stress_collection.py` for benchmarking the converter on synthetic collections. Defaults to 500 requests across deep folder trees mixing ASCII, Cyrillic, accented Latin, and CJK characters so the name-sanitiser edge cases stay exercised. Used by the `stress-test` CI job and locally when reasoning about generation speed and pytest collection limits.

```bash
# Generate a 500-request synthetic collection
python scripts/generate_stress_collection.py --requests 500 \
    --out data/stress_collection_500.json

# Convert it
postman2pytest --collection data/stress_collection_500.json --out /tmp/stress.py

# Verify the generated module collects in pytest
pytest --collect-only /tmp/stress.py | tail -5
```

If pytest collection time spikes beyond a few seconds on a 500-request collection, the regression is usually in the folder-name slugifier (Cyrillic / CJK paths produce long unique names). Re-run with `--filter-folder` to bisect.

## Error handling

- **Schema mismatch:** the converter exits non-zero with a clear message naming the unsupported schema. Re-export the collection as v2.1 in Postman.
- **File too large:** `--max-input-mb` (default 100) refuses collections above the limit. Pass a larger value if the collection is genuinely that big, or split it via `--filter-folder`.
- **Pytest failures on first run:** check `BASE_URL` is set and reachable. The generated module assumes the API is live; it does not mock responses.
- **Empty output:** the collection has no `item` array, or `--filter-folder` matched zero folders (case-insensitive). Run without the filter to confirm.

## Limitations and known gaps

- **OAuth flows:** Token refresh is not generated. Set the token in the env var named by the collection's `Authorization` header.
- **Pre-request scripts:** Postman's JavaScript pre-request scripts are not translated. Rewrite any script-computed headers or signatures in Python before running.
- **Response-body assertions:** Only the HTTP status code is asserted. Body content is not validated.
- **Environments file:** Postman environment exports (`*.postman_environment.json`) are not consumed. The generated suite reads `BASE_URL` and credential env vars only.

## CI integration

Minimal GitHub Actions workflow that runs the converter and the suite on every push:

```yaml
name: API tests
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install postman2pytest
      - run: postman2pytest --collection collection.json --out tests/test_api.py
      - run: pytest tests/test_api.py -v
        env:
          BASE_URL: ${{ secrets.STAGING_BASE_URL }}
          AUTHORIZATION: ${{ secrets.STAGING_API_TOKEN }}
```

## External links

- Project README and design write-up: https://github.com/golikovichev/postman2pytest
- Article on the bridge concept: https://dev.to/golikovichev/postman-and-pytest-are-living-in-parallel-universes-heres-a-bridge-5bgn
- PyPI package: https://pypi.org/project/postman2pytest/
