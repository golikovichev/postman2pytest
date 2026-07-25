# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-07-25

### Added

- Repeated form keys in `urlencoded` and `formdata` bodies are preserved.
  Previously a duplicate field name collapsed to its last value because the
  parser stored form fields in a dict. The parser now keeps the idiomatic dict
  when names are unique and falls back to a list of `(key, value)` pairs when a
  name repeats, so the generated `data=` argument sends every value (for
  example `scope=read&scope=write`). File-type upload fields are still skipped
  (#1).
- OpenAPI 3.x specs are accepted as an alternative input format (closes #10).
  Pass `--input-format openapi` to generate a pytest suite from an OpenAPI 3.x
  JSON or YAML spec instead of a Postman collection. A new `core/openapi_parser`
  maps each operation to the same `ParsedRequest` shape the Postman parser
  emits, so the generator and templates are unchanged: path parameters
  (`/users/{id}`), query parameters, and header parameters become `os.environ`
  placeholders, a JSON request body is built from the operation example or
  schema, the expected status is the lowest 2xx response, and operations are
  grouped by their first tag so `--filter-folder` works. Default input format
  stays `postman`, so existing behaviour is unchanged. Adds a `pyyaml`
  dependency for YAML specs.
- Auth headers now extract into a shared `auth_headers` fixture (closes #2).
  Authorization Bearer/Basic and API-key headers are detected, pulled out of
  each generated test, and centralised in an `auth_headers` fixture written to a
  generated `conftest.py`. The generated tests take the fixture and merge it
  into their headers, and each secret is replaced with an environment-variable
  placeholder (`AUTH_TOKEN` for Authorization, an upper snake-case of the header
  name otherwise), so no token lands in the generated source. Postman variables
  in an auth header become `os.environ` lookups in the fixture. The fixture is a
  union across the collection; conflicting schemes are noted in the README
  limitations.
- Postman environment variables resolve through `--env` (#22). Pass `--env
  <environment.json>` with a Postman environment export: non-secret variables
  are inlined as literal values in the generated tests, while variables marked
  secret in the export, and any variable absent from it, become named pytest
  fixtures so a secret value never lands in the generated source. Resolution
  covers URLs and headers; a name that is not a valid, non-colliding Python
  identifier falls back to an `os.environ` lookup so the file always compiles.
  Without `--env`, behaviour is unchanged.
- Property-based fuzz tests for the collection parser (Hypothesis), feeding it
  arbitrary and deliberately malformed JSON to keep its failure modes graceful.

### Fixed

- Control characters and quotes in a generated URL or docstring are now escaped.
  A newline, carriage return, tab, or quote carried through from a collection
  value could break the generated Python string literal or f-string; the value
  is escaped so the emitted test stays valid source.
- A non-dict sub-structure inside an item no longer aborts the whole parse. A
  `request`, header element, `body`, or form field arriving as a string or
  `null` made a `.get(...)` call raise `AttributeError`, which was not in the
  caught tuple, so one malformed item crashed the entire run. `AttributeError`
  is now caught alongside `KeyError` / `TypeError` / `ValueError`, so the bad
  item is skipped with a warning and the rest of the collection still parses.
  Covered by five regression cases in `tests/test_parser.py`.
- The parser no longer crashes with an unhandled `AttributeError`, `TypeError`
  or `RecursionError` on a malformed collection file. A non-object root now
  raises a clear `ValueError`; a non-object `info` or non-list `item` is
  tolerated; scalar items are skipped with a warning; and folder trees nested
  too deeply to parse raise a clear `ValueError` instead of overflowing the
  stack.

## [1.2.0] - 2026-06-16

### Added

- Test-script assertion translation: Postman `pm.test(...)` scripts are now
  parsed and translated into pytest `assert` statements instead of being
  dropped. The supported subset covers response time
  (`responseTime ... to.be.below(N)`), header presence
  (`to.have.header("X")`), and top-level JSON body field equality
  (`pm.expect(jsonData.field).to.eql(value)` and the `pm.response.json().field`
  idiom, for string / number / boolean values). Patterns outside this subset
  (arbitrary JavaScript, nested fields, schema validation) are skipped rather
  than mistranslated, so a generated test never carries a broken assert.
- Form body support: `urlencoded` and `formdata` text fields are now parsed and
  rendered into the generated request as a `data={...}` argument instead of
  being dropped. File-type `formdata` fields (uploads) are still skipped
  (partial #1).
- Status extraction now also recognises the `pm.response.code === 201` idiom
  (and the loose `==` form) in test scripts, not only
  `pm.response.to.have.status(201)`. Collections that assert status the first
  way previously fell back to the default 200, generating a test with the wrong
  expected status.

## [1.1.0] - 2026-05-23

### Added

- `--filter-folder NAME` CLI flag: generate tests only from a named Postman
  folder (closes #5, contributor PR by SHIVANSH-ux-ys).
- Python 3.13 added to supported classifiers and CI matrix.
- Input-size guard: reject Postman collection JSON files above a configurable
  maximum size to fail fast on malformed or oversize input.
- httpbin sample collection with 3 endpoints in `tests/data/` for smoke testing
  the generator end-to-end.
- Wheel-smoke CI job: builds the wheel, installs it in a clean venv, runs the
  console-script `--help`, and asserts entry-point resolution via
  `importlib.metadata`.
- Stress-test CI job: generates a 500-request synthetic collection with mixed
  Cyrillic, ASCII, accented Latin, and CJK folder names and confirms parse and
  render succeed.
- README badges for monthly downloads (pepy.tech), GitHub Sponsors, and Codecov
  coverage.
- `SKILL.md` and `REFERENCE.md` for Tessl Registry submission (review score
  97%).
- Limitations and Roadmap sections in README.

### Fixed

- Absolute URLs in Postman requests (e.g. `https://api.example.com/...`) are no
  longer prefixed with `BASE_URL`, matching Postman runtime semantics.
- Generated header f-strings now escape literal `{` and `}` so headers
  containing curly-brace text render correctly.
- Generator uses narrower exception types instead of broad `except Exception`
  blocks so genuine errors propagate clearly.

### Changed

- CI matrix expanded to macOS and Windows on Python 3.10 through 3.13.
- Documentation split: `SKILL.md` contains the quick-start surface,
  `REFERENCE.md` holds CLI flags, validation, error tree, and CI templates.
- Redundant `requirements.txt` removed; `pyproject.toml` is the single source
  of truth for dependencies.

## [1.0.2] - 2026-05-11

### Fixed

- Packaging: the wheel now includes `main.py` at the top level via a
  `force-include` directive in the hatch build config. This is the module the
  `postman2pytest` console script entry point references.

## [1.0.1] - 2026-05-11

### Fixed

- Non-ASCII folder names (Cyrillic, Chinese, Arabic, accented Latin) no longer
  produce empty test name prefixes that silently collide. Folder slugs are now
  transliterated via `unidecode` so `Заказы` becomes `zakazy` in the generated
  function name. Closes #3.
- Test names that would still collide after slugification (for example several
  requests in the same folder sharing an HTTP method and missing the Postman
  `name` field) now receive a `_1` / `_2` / `_N` suffix so every parsed request
  maps to a unique pytest function. The parser emits a warning per affected
  base name.

### Added

- `unidecode>=1.3,<2` runtime dependency for ASCII transliteration.
- 12 unit tests covering Cyrillic, Chinese, accented Latin, empty input,
  punctuation-only input, no-collision passthrough, and the exact issue #3
  reproduction.

## [1.0.0] - 2026-04-24

### Added

- `core/parser.py` - parse Postman Collection v2.1 JSON into `ParsedRequest` Pydantic models
  - Recursive folder flattening with folder prefix in test names
  - `{{variable}}` → `ENV_variable` substitution for environment-driven test execution
  - Expected status extraction from `pm.response.to.have.status(N)` test scripts
  - Disabled headers excluded automatically
  - Malformed items skipped with a warning; rest of collection continues
- `core/generator.py` - Jinja2-based pytest file renderer
  - Custom `tojson` filter for safe Python value representation
  - Creates output parent directories automatically
- `templates/test_collection.jinja2` - output template
  - One `def test_*()` function per request
  - Handles body (json=) and no-body requests separately
  - Status assertion with descriptive failure message
- `main.py` - CLI (`postman2pytest --collection ... --out ...`)
- `data/sample_collection.json` - sample Postman collection for manual testing
- 36 unit tests across `tests/test_parser.py` and `tests/test_generator.py`
- `pyproject.toml` - PyPI packaging via Hatchling, `postman2pytest` console script
- CI via GitHub Actions (Python 3.10, 3.11, 3.12)
