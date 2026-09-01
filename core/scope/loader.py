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
                    break
            else:
                targets.append(
                    {
                        "domain": domain,
                        "mode": mode,
                        "rate_limit_rps": rate_limit_rps,
                        "excluded_paths": [],
                        "notes": notes,
                    }
                )

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
