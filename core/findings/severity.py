"""Severity ranking + the query that decides which findings are worth a
Claude triage call. Kept deterministic and in Python — Claude never sees
findings that don't clear this bar."""
from __future__ import annotations

from core.db import database

SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

TRIAGE_MIN_SEVERITY = "medium"


def meets_threshold(severity: str | None, min_severity: str = TRIAGE_MIN_SEVERITY) -> bool:
    return SEVERITY_RANK.get((severity or "info").lower(), 0) >= SEVERITY_RANK[min_severity]


async def get_triage_candidates(job_id: int, limit: int = 40) -> list[dict]:
    """New findings from this job that either clear the severity bar or are
    flagged as an 'exposure' type regardless of severity (e.g. an exposed
    .git/.env is worth a look even if a template marked it 'info')."""
    rows = await database.fetchall(
        "SELECT id, target, tool, finding_type, severity, title, detail, url "
        "FROM findings WHERE job_id = ? AND status = 'new' "
        "ORDER BY "
        "CASE severity "
        " WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 "
        " WHEN 'low' THEN 1 ELSE 0 END DESC "
        "LIMIT ?",
        (job_id, limit * 3),  # overselect, then filter below, then cap
    )
    candidates = [
        dict(r) for r in rows
        if meets_threshold(r["severity"]) or r["finding_type"] == "exposure"
    ]
    return candidates[:limit]
