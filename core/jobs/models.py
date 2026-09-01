"""Job dataclass + read helpers. Writes live in queue.py (the only writer
of job state, so there's one place that owns job lifecycle transitions)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from core.db import database


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    RECON = "recon"
    XSS = "xss"
    SQLI = "sqli"
    FFUF = "ffuf"
    REPORT = "report"


@dataclass
class Job:
    id: int
    job_type: str
    target: str
    params: dict
    status: str
    created_by: str
    channel_id: str
    message_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    raw_output_dir: str | None
    error: str | None

    @classmethod
    def from_row(cls, row) -> "Job":
        return cls(
            id=row["id"],
            job_type=row["job_type"],
            target=row["target"],
            params=json.loads(row["params_json"] or "{}"),
            status=row["status"],
            created_by=row["created_by"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            raw_output_dir=row["raw_output_dir"],
            error=row["error"],
        )


async def get_job(job_id: int) -> Job | None:
    row = await database.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return Job.from_row(row) if row else None


async def list_jobs(status: str | None = None, limit: int = 20) -> list[Job]:
    if status:
        rows = await database.fetchall(
            "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)
        )
    else:
        rows = await database.fetchall("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    return [Job.from_row(r) for r in rows]
