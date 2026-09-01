"""Rolling 24h budget for headless `claude -p` calls. Every invocation is
recorded here even on failure/timeout, so a retry storm can't silently
bypass the daily cap — this is what keeps the Pro-plan usage predictable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.db import database


async def get_daily_budget() -> int:
    val = await database.get_setting("claude_daily_budget", "20")
    return int(val)


async def set_daily_budget(n: int) -> None:
    await database.set_setting("claude_daily_budget", str(n))


async def invocations_last_24h() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    row = await database.fetchone(
        "SELECT COUNT(*) AS n FROM claude_invocations WHERE timestamp > ?", (since,)
    )
    return row["n"] if row else 0


async def can_invoke() -> bool:
    budget = await get_daily_budget()
    if budget <= 0:
        return False
    return (await invocations_last_24h()) < budget


async def record(
    purpose: str,
    backend: str,
    job_id: int | None = None,
    model: str | None = None,
    duration_ms: int | None = None,
    total_cost_usd: float | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    await database.execute(
        "INSERT INTO claude_invocations "
        "(timestamp, purpose, job_id, backend, model, duration_ms, total_cost_usd, success, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            purpose,
            job_id,
            backend,
            model,
            duration_ms,
            total_cost_usd,
            1 if success else 0,
            error,
        ),
    )
