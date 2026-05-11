# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
