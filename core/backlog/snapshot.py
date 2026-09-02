"""Captures a full dump of a target's findings table into
data/backlog/<target>/<timestamp>__job<job_id>.json on every completed job,
and indexes it in backlog_snapshots for cheap lookup without re-reading
every file. capture() is the single entrypoint called from jobs/queue.py
right after a pipeline finishes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.backlog.diff import BacklogDiff, compute_diff
from core.config import BACKLOG_DIR, ensure_data_dirs
from core.db import database

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9.\-]+")


def _safe_dirname(target: str) -> str:
    return _SANITIZE_RE.sub("_", target).strip("._") or "unknown-target"


@dataclass
class Snapshot:
    target: str
    job_id: int
    job_type: str
    created_at: str
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "target": self.target,
                "job_id": self.job_id,
                "job_type": self.job_type,
                "created_at": self.created_at,
                "findings": self.findings,
            },
            default=str,
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Snapshot":
        data = json.loads(raw)
        return cls(
            target=data["target"],
            job_id=data["job_id"],
            job_type=data["job_type"],
            created_at=data["created_at"],
            findings=data.get("findings", []),
        )


def _target_dir(target: str) -> Path:
    return BACKLOG_DIR / _safe_dirname(target)


def _path_for(target: str, job_id: int, created_at: str) -> Path:
    ts = created_at.replace(":", "").replace("+00:00", "Z")
    return _target_dir(target) / f"{ts}__job{job_id}.json"


async def _latest_snapshot_row(target: str) -> dict | None:
    row = await database.fetchone(
        "SELECT * FROM backlog_snapshots WHERE target = ? ORDER BY created_at DESC LIMIT 1",
        (target,),
    )
    return dict(row) if row else None


async def load_previous(target: str) -> Snapshot | None:
    row = await _latest_snapshot_row(target)
    if row is None:
        return None
    path = Path(row["path"])
    if not path.is_file():
        return None
    return Snapshot.from_json(path.read_text())


async def capture(target: str, job_id: int, job_type: str) -> tuple[Snapshot, BacklogDiff]:
    """Reads the full current findings table for `target` (not just this
    job's rows — the point is a complete state-of-the-target picture),
    diffs it against the previous snapshot, writes the new snapshot file,
    and indexes it. Returns (current_snapshot, diff)."""
    ensure_data_dirs()

    previous = await load_previous(target)

    rows = await database.fetchall(
        "SELECT hash, tool, finding_type, severity, title, detail, url, status, "
        "priority, impact, first_seen_at, last_seen_at FROM findings WHERE target = ? ORDER BY id",
        (target,),
    )
    now = datetime.now(timezone.utc).isoformat()
    current = Snapshot(
        target=target,
        job_id=job_id,
        job_type=job_type,
        created_at=now,
        findings=[dict(r) for r in rows],
    )

    diff = compute_diff(previous, current)

    path = _path_for(target, job_id, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current.to_json())

    await database.execute(
        "INSERT INTO backlog_snapshots "
        "(target, job_id, path, created_at, total_findings, new_since_last, not_redetected_since_last, diff_summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            target,
            job_id,
            str(path),
            now,
            len(current.findings),
            len(diff.new_findings),
            len(diff.not_redetected),
            diff.human_summary(),
        ),
    )

    return current, diff


async def list_snapshots(target: str, limit: int = 20) -> list[dict]:
    rows = await database.fetchall(
        "SELECT id, job_id, created_at, total_findings, new_since_last, "
        "not_redetected_since_last, diff_summary FROM backlog_snapshots "
        "WHERE target = ? ORDER BY created_at DESC LIMIT ?",
        (target, limit),
    )
    return [dict(r) for r in rows]
