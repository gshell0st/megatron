"""The "beyond compare" step: a pure function comparing two full-table
snapshots of a target's findings and surfacing what changed. No I/O here —
snapshot.py handles loading/saving, this just diffs two in-memory objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.backlog.snapshot import Snapshot

_TRACKED_HOST_TYPES = ("subdomain", "live-host")


@dataclass
class BacklogDiff:
    target: str
    is_first_scan: bool
    previous_scan_at: str | None = None
    new_findings: list[dict[str, Any]] = field(default_factory=list)
    not_redetected: list[dict[str, Any]] = field(default_factory=list)
    new_hosts: list[str] = field(default_factory=list)
    carried_over_count: int = 0

    def human_summary(self) -> str:
        if self.is_first_scan:
            return "Primeiro teste registrado para este alvo — sem historico pra comparar ainda."
        parts = [f"Beyond compare vs {self.previous_scan_at}:"]
        parts.append(f"{len(self.new_findings)} achado(s) novo(s)")
        if self.new_hosts:
            parts.append(f"{len(self.new_hosts)} host(s) novo(s)")
        if self.not_redetected:
            parts.append(
                f"{len(self.not_redetected)} achado(s) anterior(es) nao redetectado(s) "
                f"(pode ter sido corrigido, ou o host caiu — vale confirmar)"
            )
        parts.append(f"{self.carried_over_count} inalterado(s)")
        return ", ".join(parts).replace(":,", ":")


def compute_diff(previous: "Snapshot | None", current: "Snapshot") -> BacklogDiff:
    if previous is None:
        return BacklogDiff(
            target=current.target,
            is_first_scan=True,
            new_findings=list(current.findings),
            new_hosts=[
                f["title"] for f in current.findings if f["finding_type"] in _TRACKED_HOST_TYPES
            ],
        )

    prev_by_hash = {f["hash"]: f for f in previous.findings}
    curr_by_hash = {f["hash"]: f for f in current.findings}

    new_hashes = curr_by_hash.keys() - prev_by_hash.keys()
    new_findings = [curr_by_hash[h] for h in new_hashes]

    # A finding present before that this run didn't re-touch (its
    # last_seen_at wasn't bumped past the previous snapshot's timestamp) is
    # a candidate for "fixed or host went away" — upsert_finding() refreshes
    # last_seen_at on every re-detection, so a stale timestamp here is a
    # real signal, not an assumption.
    not_redetected = [
        prev_by_hash[h]
        for h in prev_by_hash
        if h in curr_by_hash and curr_by_hash[h]["last_seen_at"] <= previous.created_at
    ]

    new_hosts = [f["title"] for f in new_findings if f["finding_type"] in _TRACKED_HOST_TYPES]
    carried_over = len(curr_by_hash.keys() & prev_by_hash.keys()) - len(not_redetected)

    return BacklogDiff(
        target=current.target,
        is_first_scan=False,
        previous_scan_at=previous.created_at,
        new_findings=new_findings,
        not_redetected=not_redetected,
        new_hosts=new_hosts,
        carried_over_count=max(0, carried_over),
    )
