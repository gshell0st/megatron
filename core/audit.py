"""Every action the system takes — command invocations, scope decisions, job
lifecycle, Claude calls — gets written here. Two copies on purpose: the DB
row is queryable, the log line is grep-able even if the DB is locked/corrupt.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from core.config import LOGS_DIR, ensure_data_dirs
from core.db import database

_AUDIT_LOG_PATH = LOGS_DIR / "audit.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log(
    actor: str,
    action: str,
    target: str | None = None,
    tool: str | None = None,
    job_id: int | None = None,
    **details: object,
) -> None:
    ensure_data_dirs()
    ts = _now()
    details_json = json.dumps(details, default=str) if details else "{}"

    await database.execute(
        "INSERT INTO audit_log (timestamp, actor, action, target, tool, job_id, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, actor, action, target, tool, job_id, details_json),
    )

    line = f"{ts} actor={actor} action={action} target={target} tool={tool} job_id={job_id} {details_json}\n"
    with _AUDIT_LOG_PATH.open("a") as f:
        f.write(line)
