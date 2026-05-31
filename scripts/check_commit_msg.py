#!/usr/bin/env python
"""Commit-message style scanner: keeps the subject line concrete.

Runs at the `commit-msg` stage of pre-commit. Fails the commit when the
subject is a vague verb-only chore or uses one of a short list of
prose-cleanup framing words that read as bulk-edit boilerplate rather
than concrete technical motivation.

Banned subject phrases (case-insensitive, word-bounded):
    cleanup, hygiene, sweep, polish

Also rejects subjects that are only "chore: cleanup" / "docs: polish"
shaped without any follow-up scope.

Exit code 0 = clean, 1 = at least one finding.

Usage:
    python scripts/check_commit_msg.py .git/COMMIT_EDITMSG
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns built from concatenation so this source file itself stays
# scannable without self-matches in the smoke tests.
_BANNED_TOKENS = (
    "clean" + "up",
    "hygiene",
    "sweep",
    "polish",
)
BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(tok) for tok in _BANNED_TOKENS) + r")\b",
    re.IGNORECASE,
)

# Subjects that are just a vague verb with no scope.
VAGUE_SUBJECT_RE = re.compile(
    r"^\s*(chore|docs|refactor|build)\s*:\s*(clean" + r"up|hygiene|sweep|polish)\s*$",
    re.IGNORECASE,
)


def scan(message: str) -> list[str]:
    findings: list[str] = []
    lines = message.splitlines()
    subject = lines[0] if lines else ""

    if VAGUE_SUBJECT_RE.match(subject):
        findings.append(f"subject is vague verb without scope: {subject!r}")

    for token_match in BANNED_RE.finditer(subject):
        token = token_match.group(0)
        findings.append(f"prose-cleanup framing in subject: {token!r}")

    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "check_commit_msg: expected a commit message file path",
            file=sys.stderr,
        )
        return 2

    msg_path = Path(argv[1])
    try:
        text = msg_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"check_commit_msg: cannot read {msg_path}: {exc}", file=sys.stderr)
        return 2

    # Strip git's comment lines so they don't trigger findings.
    payload = "\n".join(line for line in text.splitlines() if not line.startswith("#"))

    findings = scan(payload)
    if not findings:
        return 0

    print("Commit subject reads as a bulk prose-edit. Fix:", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
    print(
        "\nUse a concrete technical scope instead, for example:\n"
        "  docs(security): document supported versions and reporting flow\n"
        "  refactor(api): drop unused parser fallback path\n"
        "  fix(text): replace em-dash with ASCII hyphen in ten files",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
