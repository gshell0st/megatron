"""Loads and edits scope.yaml.

Uses ruamel.yaml's round-trip loader so that /scope add|remove commands can
rewrite the file via Discord without destroying the owner's comments and
formatting when they hand-edit it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from ruamel.yaml import YAML

from core.config import SCOPE_PATH

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


@dataclass(frozen=True)
class ScopeEntry:
    domain: str
    mode: str  # "passive" | "active"
    rate_limit_rps: float
    excluded_paths: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    # Set when this entry came from (or is linked to) a bug bounty platform
    # program — lets /submit know where a report for this target should go,
    # and lets HackerOne submissions reference the exact scope item.
    platform: str | None = None  # "hackerone" | "intigriti"
    program_handle: str | None = None
    platform_scope_id: int | None = None


class ScopeStore:
    """In-memory view of scope.yaml, reloadable, with write-back support."""

    def __init__(self, path: Path = SCOPE_PATH):
        self._path = path
        self._lock = Lock()
        self._entries: list[ScopeEntry] = []
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._entries = []
                return
            data = _yaml.load(self._path.read_text()) or {}
            entries = []
            for raw in data.get("targets", []) or []:
                entries.append(
                    ScopeEntry(
                        domain=str(raw["domain"]).strip().lower(),
                        mode=str(raw.get("mode", "passive")).strip().lower(),
                        rate_limit_rps=float(raw.get("rate_limit_rps", 5)),
                        excluded_paths=tuple(raw.get("excluded_paths") or []),
                        notes=str(raw.get("notes", "")),
                        platform=raw.get("platform"),
                        program_handle=raw.get("program_handle"),
                        platform_scope_id=raw.get("platform_scope_id"),
                    )
                )
            self._entries = entries

    def list(self) -> list[ScopeEntry]:
        with self._lock:
            return list(self._entries)

    def add(
        self,
        domain: str,
        mode: str = "passive",
        rate_limit_rps: float = 5,
        notes: str = "",
        platform: str | None = None,
        program_handle: str | None = None,
        platform_scope_id: int | None = None,
    ) -> None:
        domain = domain.strip().lower()
        if mode not in ("passive", "active"):
            raise ValueError("mode must be 'passive' or 'active'")

        with self._lock:
            data = _yaml.load(self._path.read_text()) if self._path.exists() else None
            if data is None:
                data = {"targets": []}
            targets = data.setdefault("targets", [])

            for t in targets:
                if str(t.get("domain", "")).strip().lower() == domain:
                    t["mode"] = mode
                    t["rate_limit_rps"] = rate_limit_rps
                    if notes:
                        t["notes"] = notes
                    if platform:
                        t["platform"] = platform
                    if program_handle:
                        t["program_handle"] = program_handle
                    if platform_scope_id is not None:
                        t["platform_scope_id"] = platform_scope_id
                    break
            else:
                new_entry = {
                    "domain": domain,
                    "mode": mode,
                    "rate_limit_rps": rate_limit_rps,
                    "excluded_paths": [],
                    "notes": notes,
                }
                if platform:
                    new_entry["platform"] = platform
                if program_handle:
                    new_entry["program_handle"] = program_handle
                if platform_scope_id is not None:
                    new_entry["platform_scope_id"] = platform_scope_id
                targets.append(new_entry)

            with self._path.open("w") as f:
                _yaml.dump(data, f)

        self.reload()

    def remove(self, domain: str) -> bool:
        domain = domain.strip().lower()
        with self._lock:
            if not self._path.exists():
                return False
            data = _yaml.load(self._path.read_text()) or {}
            targets = data.get("targets", []) or []
            new_targets = [
                t for t in targets if str(t.get("domain", "")).strip().lower() != domain
            ]
            removed = len(new_targets) != len(targets)
            if removed:
                data["targets"] = new_targets
                with self._path.open("w") as f:
                    _yaml.dump(data, f)

        if removed:
            self.reload()
        return removed


_store: ScopeStore | None = None


def get_scope_store() -> ScopeStore:
    global _store
    if _store is None:
        _store = ScopeStore()
    return _store
