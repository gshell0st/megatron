"""Rolling 24h budget for headless `claude -p` calls. Every invocation is
recorded here even on failure/timeout, so a retry storm can't silently
bypass the daily cap — this is what keeps the Pro-plan usage predictable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from core.db import database

ALERT_THRESHOLD = 0.8
ALERT_MIN_INTERVAL_HOURS = 6
_ALERT_LAST_SENT_KEY = "quota_alert_last_sent"

AlertHook = Callable[[int, int, float], Awaitable[None]]
_alert_hook: AlertHook | None = None


def set_alert_hook(hook: AlertHook | None) -> None:
    """Registered by bot/client.py so this module can push a Discord
    notification without core/ importing anything Discord-specific."""
    global _alert_hook
    _alert_hook = hook


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


async def maybe_alert_threshold() -> None:
    """Call after anything that could change usage (a recorded invocation)
    or on a timer (the hourly heartbeat) — cheap to call often since it's
    a no-op below the threshold and rate-limited above it."""
    budget = await get_daily_budget()
    if budget <= 0 or _alert_hook is None:
        return

    used = await invocations_last_24h()
    ratio = used / budget

    if ratio < ALERT_THRESHOLD:
        await database.set_setting(_ALERT_LAST_SENT_KEY, "")
        return

    last_sent_raw = await database.get_setting(_ALERT_LAST_SENT_KEY, "")
    if last_sent_raw:
        last_sent = datetime.fromisoformat(last_sent_raw)
        if datetime.now(timezone.utc) - last_sent < timedelta(hours=ALERT_MIN_INTERVAL_HOURS):
            return

    await database.set_setting(_ALERT_LAST_SENT_KEY, datetime.now(timezone.utc).isoformat())
    await _alert_hook(used, budget, ratio)


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
