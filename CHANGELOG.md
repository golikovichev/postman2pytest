# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
