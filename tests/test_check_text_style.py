"""Tests for scripts/check_text_style.py.

Every "bad" input is built from unicode escapes so this test file stays pure
ASCII. That keeps it from tripping the scanner it exercises and from ruff's
ambiguous-unicode rules, while still feeding real non-ASCII bytes to scan_file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_text_style.py"
_spec = importlib.util.spec_from_file_location("check_text_style", _SCRIPT)
cts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cts)

EM_DASH = chr(0x2014)
LDQUO, RDQUO = chr(0x201C), chr(0x201D)
CYR_V = chr(0x432)  # Cyrillic small "ve"
CYR_A = chr(0x430)  # Cyrillic small "a", homoglyph of Latin a
CYR_E = chr(0x435)  # Cyrillic small "ie", homoglyph of Latin e
PRIVET = "".join(chr(c) for c in (0x43F, 0x440, 0x438, 0x432, 0x435, 0x442))  # a Cyrillic word


def _write(tmp_path: Path, text: str, name: str = "sample.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_ascii_passes(tmp_path):
    p = _write(tmp_path, "This is plain ASCII prose with no problems.\n")
    assert cts.scan_file(p) == []


def test_em_dash_flagged(tmp_path):
    p = _write(tmp_path, f"A sentence {EM_DASH} with an em dash.\n")
    assert any("em-dash" in f for f in cts.scan_file(p))


def test_curly_quote_flagged(tmp_path):
    p = _write(tmp_path, f"He said {LDQUO}hello{RDQUO} loudly.\n")
    assert any("curly quote" in f for f in cts.scan_file(p))


def test_buzzword_flagged(tmp_path):
    p = _write(tmp_path, "We leverage a robust solution.\n")
    assert any("buzzword" in f for f in cts.scan_file(p))


def test_standalone_cyrillic_v_flagged(tmp_path):
    p = _write(tmp_path, f"the data lives {CYR_V} memory now\n")
    assert any("Cyrillic" in f for f in cts.scan_file(p))


def test_homoglyph_inside_latin_word_flagged(tmp_path):
    # "latency" with a Cyrillic 'e' swapped in.
    p = _write(tmp_path, f"measured the lat{CYR_E}ncy of each call\n")
    findings = cts.scan_file(p)
    assert any("mixed-script" in f.lower() for f in findings), findings


def test_homoglyph_cyrillic_a_inside_word_flagged(tmp_path):
    # "data" with a Cyrillic 'a'.
    p = _write(tmp_path, f"the d{CYR_A}ta pipeline is slow\n")
    assert any("mixed-script" in f.lower() for f in cts.scan_file(p))


def test_pure_cyrillic_word_not_flagged_as_mixed(tmp_path):
    # A wholly Cyrillic word is legitimate Russian text, not a within-word mix.
    p = _write(tmp_path, f"{PRIVET} team\n")
    findings = cts.scan_file(p)
    assert not any("mixed-script" in f.lower() for f in findings), findings


def test_find_mixed_script_word_helper():
    assert cts.find_mixed_script_word(f"d{CYR_A}ta") == f"d{CYR_A}ta"
    assert cts.find_mixed_script_word("data") is None
    assert cts.find_mixed_script_word(PRIVET) is None


def test_skip_names_ignored(tmp_path):
    p = _write(tmp_path, f"He said {LDQUO}hi{RDQUO}\n", name="CHANGELOG.md")
    assert cts.scan_file(p) == []


def test_non_allowed_suffix_ignored(tmp_path):
    p = _write(tmp_path, f"A sentence {EM_DASH} dash\n", name="image.png")
    assert cts.scan_file(p) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
