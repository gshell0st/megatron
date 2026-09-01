"""Deterministic hashing so the same finding seen across repeated recon
runs updates last_seen_at instead of creating a duplicate row — this is
also what lets the Claude triage step ask for only 'new' findings.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from core.db import database


def finding_hash(tool: str, target: str, finding_type: str, detail: str | None, title: str) -> str:
    normalized = "|".join(
        [tool, target, finding_type, (detail or "").strip().lower(), title.strip().lower()]
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


async def upsert_finding(
    job_id: int,
    target: str,
    tool: str,
    raw: dict[str, Any],
) -> tuple[int, bool]:
    """Insert a new finding or refresh last_seen_at on an existing one.
    Returns (finding_id, is_new)."""
    now = datetime.now(timezone.utc).isoformat()
    finding_type = raw["finding_type"]
    title = raw["title"]
    detail = raw.get("detail")
    url = raw.get("url")
    severity = raw.get("severity")
    h = finding_hash(tool, target, finding_type, detail, title)

    existing = await database.fetchone("SELECT id FROM findings WHERE hash = ?", (h,))
    if existing:
        await database.execute(
            "UPDATE findings SET last_seen_at = ?, job_id = ? WHERE id = ?",
            (now, job_id, existing["id"]),
        )
        return existing["id"], False

    finding_id = await database.execute(
        "INSERT INTO findings "
        "(job_id, target, tool, finding_type, severity, title, detail, url, hash, status, first_seen_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)",
        (job_id, target, tool, finding_type, severity, title, detail, url, h, now, now),
    )
    return finding_id, True


async def set_finding_status(finding_id: int, status: str) -> None:
    await database.execute("UPDATE findings SET status = ? WHERE id = ?", (status, finding_id))
