# Contributing to postman2pytest

Thank you for your interest in contributing!

## Setup

```bash
git clone https://github.com/golikovichev/postman2pytest
cd postman2pytest
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install pytest
```

## Running tests

```bash
pytest tests/ -v --tb=short
```

All tests must pass before opening a PR.

## Project structure

```
core/
  parser.py     — Postman JSON → ParsedRequest objects
  generator.py  — ParsedRequest list → pytest file via Jinja2
templates/
  test_collection.jinja2  — output template
tests/
  test_parser.py    — unit tests for parser
  test_generator.py — unit tests for generator
main.py           — CLI entry point
data/             — sample collections for manual testing
```

## Submitting changes

1. Fork the repo and create a branch: `git checkout -b feat/my-change`
2. Write tests for new behaviour
3. Ensure `pytest tests/ -v` passes
4. Open a pull request with a clear description of the change and motivation

## Code style

- Python 3.10+ type hints throughout
- No external dependencies beyond `pydantic`, `jinja2`, `requests`
- Keep `core/parser.py` free of business logic unrelated to parsing
- Keep `core/generator.py` thin — logic belongs in the template or the model
