"""Regex-based secret detection for the body of a confirmed-exposed file
(.env, backup, config). Deliberately narrow, high-signal patterns — this
runs only after a path has already cleared the soft-404 filter, so a false
positive here means "we downloaded this file and it merely looks like it
contains a secret," which is a fine bar for surfacing to the impact-first
triage step rather than a bar for outright reporting.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,48}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    (
        "DB connection string with credentials",
        re.compile(r"(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis)://[^\s'\"]+:[^\s'\"@]+@[^\s'\"]+"),
    ),
    (
        "Generic API key/secret assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|password|passwd)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_\-/+]{12,}['\"]?"
        ),
    ),
]


def _redact(value: str) -> str:
    if len(value) <= 14:
        return "*" * len(value)
    return f"{value[:6]}…redacted…{value[-4:]}"


def find_secrets(text: str, max_matches: int = 10) -> list[dict[str, str]]:
    """Returns [{"kind": ..., "excerpt": redacted}], deduped by kind+excerpt,
    capped so one file with a repeated pattern doesn't flood the caller."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            excerpt = _redact(m.group(0).strip())
            key = (kind, excerpt)
            if key in seen:
                continue
            seen.add(key)
            found.append({"kind": kind, "excerpt": excerpt})
            if len(found) >= max_matches:
                return found
    return found
