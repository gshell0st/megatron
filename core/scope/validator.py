"""The scope gate. Every code path that is about to touch a real target MUST
call require_scope() (or is_in_scope()) first — this is the single hard
safety invariant of the whole project. Never bypass it, never cache its
result across calls, never trust a value that didn't just come from here.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from core.scope.loader import ScopeEntry, get_scope_store


class ScopeViolation(Exception):
    """Raised when a target is not authorized, or the requested action
    exceeds what scope.yaml permits for it (e.g. active scan on a
    passive-only target)."""


def normalize_host(raw_target: str) -> str:
    """Accepts a bare domain, a URL, or host:port and returns a bare
    lowercase hostname."""
    target = raw_target.strip().lower()
    if "://" not in target:
        target = f"//{target}"
    host = urlsplit(target).hostname
    if not host:
        raise ScopeViolation(f"Could not parse a hostname from '{raw_target}'")
    return host


def is_in_scope(raw_target: str) -> ScopeEntry | None:
    """Exact match first, then subdomain-suffix match against scope.yaml."""
    host = normalize_host(raw_target)
    entries = get_scope_store().list()

    for entry in entries:
        if host == entry.domain:
            return entry
    for entry in entries:
        if host.endswith("." + entry.domain):
            return entry
    return None


def require_scope(raw_target: str, require_active: bool = False) -> ScopeEntry:
    """Returns the matching ScopeEntry or raises ScopeViolation. Pass
    require_active=True for anything beyond passive recon (ffuf/dalfox/
    sqlmap/etc) — a passive-only entry will be rejected."""
    entry = is_in_scope(raw_target)
    if entry is None:
        raise ScopeViolation(
            f"'{raw_target}' is not in scope.yaml — refusing to test it."
        )
    if require_active and entry.mode != "active":
        raise ScopeViolation(
            f"'{raw_target}' is only authorized for passive recon "
            f"(mode={entry.mode}) — active scanning is not permitted."
        )
    return entry
