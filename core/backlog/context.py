"""The "RAG idea" the retest workflow needs: instead of a vector DB (way
overkill for one target's history), retrieve grounding context deterministically
from data already on hand — the diff just computed, plus this target's own
past Claude triage verdicts (persisted on findings.priority/impact/triage_note
by jobs/queue.py after every triage call). Retrieval key is finding_type+tool,
which is exactly the axis new findings need precedent on ("last time an exposed
.env on this target was flagged, what did we conclude?"). Kept small and
capped — this rides in the same triage prompt, not a separate Claude call.
"""
from __future__ import annotations

from typing import Any

from core.backlog.diff import BacklogDiff
from core.db import database

_MAX_PRECEDENTS_PER_FINDING = 2
_MAX_PRECEDENTS_TOTAL = 8


async def _past_verdicts(target: str, tool: str, finding_type: str) -> list[dict[str, Any]]:
    rows = await database.fetchall(
        "SELECT title, status, priority, impact FROM findings "
        "WHERE target = ? AND tool = ? AND finding_type = ? "
        "AND status NOT IN ('new', 'needs-review') AND impact IS NOT NULL "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (target, tool, finding_type, _MAX_PRECEDENTS_PER_FINDING),
    )
    return [dict(r) for r in rows]


async def build_triage_context(target: str, diff: BacklogDiff) -> dict[str, Any] | None:
    """Returns None on a first scan (no history to ground anything in) so
    the triage prompt stays exactly as it was before this feature existed."""
    if diff.is_first_scan:
        return None

    seen_keys: set[tuple[str, str]] = set()
    related_past_verdicts: list[dict[str, Any]] = []
    for f in diff.new_findings:
        key = (f["tool"], f["finding_type"])
        if key in seen_keys or len(related_past_verdicts) >= _MAX_PRECEDENTS_TOTAL:
            continue
        seen_keys.add(key)
        for precedent in await _past_verdicts(target, *key):
            related_past_verdicts.append(precedent)
            if len(related_past_verdicts) >= _MAX_PRECEDENTS_TOTAL:
                break

    return {
        "previous_scan_at": diff.previous_scan_at,
        "new_since_last_scan": len(diff.new_findings),
        "not_redetected_since_last_scan": [
            {"title": f["title"], "finding_type": f["finding_type"], "first_seen_at": f["first_seen_at"]}
            for f in diff.not_redetected
        ],
        "related_past_verdicts": related_past_verdicts,
    }
