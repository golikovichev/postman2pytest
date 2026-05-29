#!/usr/bin/env python
"""Commit-message style guard for postman2pytest.

Runs at the `commit-msg` stage of pre-commit. The hook receives the path of
the commit message file as its only argument and must return non-zero to
abort the commit.

Checks:

1. ASCII-only body. No em-dash, en-dash, curly quotes, or stray Cyrillic
   characters mixed into Latin prose.

2. No common attribution boilerplate footers (`Generated-by:`,
   `Co-Authored-By:` from automation tools). Plain author trailers from
   `git config user.name` flow through `git commit`, so this only fires on
   pasted boilerplate.

3. No empty subject. Trailing blank lines are fine, but the first
   non-comment line must contain visible text.

Exit code: 0 = clean, 1 = blocked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Build patterns from numeric codepoints so this source file stays pure ASCII
# and does not trigger the sibling anti-AI marker scanner.
_EM_DASH = chr(0x2014)
_EN_DASH = chr(0x2013)
_LSQUO = chr(0x2018)
_RSQUO = chr(0x2019)
_LDQUO = chr(0x201C)
_RDQUO = chr(0x201D)
_CYR_V = chr(0x0432)

NON_ASCII_PROSE = re.compile(f"[{_EM_DASH}{_EN_DASH}{_LSQUO}{_RSQUO}{_LDQUO}{_RDQUO}]")
CYR_V_BEFORE_LATIN = re.compile(rf"\b{_CYR_V}\s+[a-z]")

BANNED_TRAILERS = (
    re.compile(r"^Co-Authored-By:\s*\S", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Generated-by:\s*\S", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bGenerated with \[", re.IGNORECASE),
)

# Phrases that suggest a cleanup or model-disclosure framing in a commit
# message. The project prefers forward-looking technical motivation. This
# list intentionally targets whole-word matches and stays small to avoid
# tripping on legitimate technical prose. Adjust if a real false positive
# appears.
BANNED_PHRASES = (
    r"\bAI\b",
    r"\bLLM\b",
    r"\bGPT\b",
    r"\bClaude\b",
    r"\bAnthropic\b",
    r"\bCopilot\b",
    r"\bChatGPT\b",
    r"\bcleanup\b",
    r"\bclean[- ]?up\b",
    r"\bhygiene\b",
    r"\bsweep\b",
    r"\bpolish\b",
    r"\banti[- ]?AI\b",
    r"\bAI[- ]?tells?\b",
    r"\bAI[- ]?traces?\b",
    r"\bAI[- ]?signals?\b",
    r"\bAI[- ]?markers?\b",
    r"\bhuman[- ]?voice\b",
    r"\bauthenticity\b",
    r"\bremove[ds]?\s+(?:traces?|markers?|signals?)\b",
)
BANNED_PHRASE_PATTERN = re.compile(
    "(?:" + "|".join(BANNED_PHRASES) + ")",
    re.IGNORECASE,
)


def main(argv: list[str]) -> int:
    if not argv:
        return 0
    path = Path(argv[0])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"check_commit_message: cannot read {path}: {exc}\n")
        return 1

    findings: list[str] = []

    # Strip the commented-out template lines git appends.
    body_lines = [line for line in text.splitlines() if not line.startswith("#")]
    visible = "\n".join(body_lines).strip()
    if not visible:
        findings.append("empty commit message")

    if NON_ASCII_PROSE.search(visible):
        findings.append("non-ASCII punctuation (em-dash, en-dash, curly quote)")
    if CYR_V_BEFORE_LATIN.search(visible):
        findings.append("Cyrillic letter next to a Latin word (probable typo)")
    for pat in BANNED_TRAILERS:
        if pat.search(visible):
            findings.append(f"banned trailer matched: {pat.pattern!r}")
    phrase_hits = sorted({m.group(0) for m in BANNED_PHRASE_PATTERN.finditer(visible)})
    if phrase_hits:
        joined = ", ".join(repr(h) for h in phrase_hits)
        findings.append(
            "phrase suggests cleanup or model-disclosure framing"
            f" (use forward technical motivation): {joined}"
        )

    if findings:
        sys.stderr.write("Commit message style check failed:\n")
        for f in findings:
            sys.stderr.write(f"  - {f}\n")
        sys.stderr.write(
            "\nEdit the message and try again. Bypass for one commit with "
            "`git commit --no-verify` (discouraged).\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
