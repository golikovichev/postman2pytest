#!/usr/bin/env python
"""Pre-commit scanner for prose style and typography in staged text files.

Fails if any of the following are present in `.py`, `.md`, `.toml`, `.yaml`,
`.yml`, `.cfg`, `.ini`, `.txt`, or `.rst` files:

- Em-dash (U+2014) or en-dash (U+2013)
- Curly quotes (U+2018, U+2019, U+201C, U+201D)
- A short list of overused buzzwords that read as boilerplate copy
- Cyrillic letters that sit next to a Latin word (typo from copy-paste)

The rationale is project policy: ASCII punctuation for cross-platform terminal
compatibility and direct ESL-friendly prose. The script is meant to be wired
through the `pre-commit` framework and to run on whichever files pre-commit
passes in on stdin via argv.

Usage:
    python scripts/check_text_style.py path/to/file.py path/to/other.md

Exit code 0 = clean, 1 = at least one finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Files we never want to scan even if pre-commit hands them to us.
SKIP_NAMES = {
    "check_text_style.py",  # this script lists the patterns by design
    "CHANGELOG.md",
    "CHANGES.md",
}

ALLOWED_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".txt",
    ".rst",
}

# Build patterns from unicode escapes so this source file stays pure ASCII
# and does not trigger either its own scanner or ruff's RUF001 rule.
_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_LSQUO = "\u2018"
_RSQUO = "\u2019"
_LDQUO = "\u201c"
_RDQUO = "\u201d"

DASH_PATTERN = re.compile(f"[{_EM_DASH}{_EN_DASH}]")
CURLY_QUOTES_PATTERN = re.compile(f"[{_LSQUO}{_RSQUO}{_LDQUO}{_RDQUO}]")

# Conservative buzzword list. Each is matched as a whole word, case-insensitive.
# Keep it short to limit false positives in legitimate prose.
BUZZWORDS = (
    "leverage",
    "leverages",
    "leveraging",
    "robust",
    "comprehensive",
    "delve",
    "delves",
    "delving",
    "navigate",
    "navigates",
    "navigating",
    "pivotal",
    "underscores",
    "seamlessly",
    "holistic",
    "paramount",
    "indispensable",
    "ever-evolving",
    "testament",
    "intricacies",
    "myriad",
)
BUZZWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BUZZWORDS) + r")\b",
    re.IGNORECASE,
)

# Mixed-script noise: Cyrillic small letter "в" (U+0432) preceded by a word
# boundary and followed by ASCII whitespace + a Latin lowercase letter. Common
# typo when copy-pasting from a Cyrillic editor into English prose.
_CYR_V = "в"
MIXED_SCRIPT_PATTERN = re.compile(rf"\b{_CYR_V}\s+[a-z]")


def scan_file(path: Path) -> list[str]:
    """Return a list of human-readable findings for one file."""
    if path.name in SKIP_NAMES:
        return []
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if DASH_PATTERN.search(line):
            findings.append(
                f"{path}:{lineno}: em-dash or en-dash (use ASCII '-', ':', or restructure)"
            )
        if CURLY_QUOTES_PATTERN.search(line):
            findings.append(f"{path}:{lineno}: curly quote (use straight ASCII quotes)")
        for match in BUZZWORD_PATTERN.finditer(line):
            findings.append(
                f"{path}:{lineno}: buzzword {match.group(0)!r} (reword in plain technical English)"
            )
        if MIXED_SCRIPT_PATTERN.search(line):
            findings.append(f"{path}:{lineno}: Cyrillic 'в' next to a Latin word (use ASCII 'in')")
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        return 0
    all_findings: list[str] = []
    for raw in argv:
        all_findings.extend(scan_file(Path(raw)))
    if all_findings:
        sys.stderr.write("Text style check failed:\n")
        for finding in all_findings:
            sys.stderr.write(f"  {finding}\n")
        sys.stderr.write(
            "\nFix the lines above and stage the result. "
            "Bypass for a single commit with: git commit --no-verify (discouraged).\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
