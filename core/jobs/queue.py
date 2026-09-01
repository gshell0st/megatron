"""The single asyncio-based job queue. One worker task per
MEGATRON_MAX_CONCURRENT_JOBS, checking the DB-backed pause flag before
running anything. This is intentionally the only writer of `jobs.status`.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Awaitable, Callable

from core.audit import log as audit_log
from core.claude_bridge import invoke as claude_invoke
from core.claude_bridge import quota as claude_quota
from core.claude_bridge.invoke import ClaudeInvocationError
from core.config import Settings
from core.db import database
from core.findings.dedup import set_finding_status
from core.findings.severity import get_triage_candidates
from core.jobs import runner
from core.pipelines.recon import run_recon_pipeline
from core.scope.validator import ScopeViolation, require_scope

_VERDICT_TO_STATUS = {
    "true-positive-likely": "reviewed-priority",
    "needs-manual-verification": "needs-review",
    "likely-noise": "reviewed-low",
}

ProgressHook = Callable[[int, str], Awaitable[None]]
SingleJobProgress = Callable[[str], Awaitable[None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobQueue:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._progress_hook: ProgressHook | None = None

    def set_progress_hook(self, hook: ProgressHook) -> None:
        self._progress_hook = hook

    async def start(self) -> None:
        for _ in range(max(1, self.settings.max_concurrent_jobs)):
            self._workers.append(asyncio.create_task(self._worker_loop()))

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()

    async def enqueue(
        self,
        job_type: str,
        target: str,
        created_by: str,
        channel_id: str,
        params: dict | None = None,
    ) -> int:
        job_id = await database.execute(
            "INSERT INTO jobs (job_type, target, params_json, status, created_by, channel_id, created_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?, ?)",
            (job_type, target, json.dumps(params or {}), created_by, channel_id, _now()),
        )
        await self._queue.put(job_id)
        await audit_log(created_by, f"job:enqueue:{job_type}", target=target, job_id=job_id)
        return job_id

    async def cancel(self, job_id: int) -> bool:
        row = await database.fetchone("SELECT status FROM jobs WHERE id = ?", (job_id,))
        if row is None or row["status"] not in ("queued", "running"):
            return False

        if row["status"] == "running":
            runner.cancel_all_for_job(job_id)

        await database.execute(
            "UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (_now(), job_id)
        )
        return True

    async def _is_paused(self) -> bool:
        return (await database.get_setting("paused", "0")) == "1"

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                while await self._is_paused():
                    await asyncio.sleep(3)
                if self.settings.emergency_stop:
                    await database.execute(
                        "UPDATE jobs SET status='cancelled', error='MEGATRON_EMERGENCY_STOP is set' WHERE id=?",
                        (job_id,),
                    )
                    continue
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a bad job must never kill the worker
                await database.execute(
                    "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                    (str(e), _now(), job_id),
                )
                await audit_log("system", "job:error", job_id=job_id, error=str(e))
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: int) -> None:
        row = await database.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None or row["status"] == "cancelled":
            return

        target = row["target"]
        job_type = row["job_type"]
        await database.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=?", (_now(), job_id)
        )

        async def progress(msg: str) -> None:
            if self._progress_hook:
                await self._progress_hook(job_id, msg)

        try:
            scope = require_scope(target, require_active=(job_type != "recon"))
        except ScopeViolation as e:
            await database.execute(
                "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                (str(e), _now(), job_id),
            )
            await audit_log("system", "scope:reject", target=target, job_id=job_id, reason=str(e))
            await progress(f"Bloqueado pelo scope gate: {e}")
            return

        if job_type == "recon":
            summary = await run_recon_pipeline(
                self.settings, target, scope, job_id, progress_cb=progress
            )
        else:
            raise NotImplementedError(f"job type '{job_type}' is not implemented yet (Phase 2)")

        await database.execute(
            "UPDATE jobs SET status='done', finished_at=? WHERE id=?", (_now(), job_id)
        )
        await audit_log(
            "system",
            "job:done",
            target=target,
            job_id=job_id,
            new_findings=summary.new_count,
            total_findings=summary.total_count,
        )
        await progress(
            f"Job concluido: {summary.new_count} achados novos ({summary.total_count} no total)."
        )

        await self._maybe_triage(job_id, target, progress)

    async def _maybe_triage(self, job_id: int, target: str, progress: SingleJobProgress) -> None:
        """Economical-brain gate: Claude is invoked at most once here, per
        job, and only if there's something in this job worth its attention."""
        candidates = await get_triage_candidates(job_id)
        if not candidates:
            await progress("Sem achados relevantes para triagem — nada enviado ao Claude.")
            return

        if not await claude_quota.can_invoke():
            await progress(
                f"Quota diaria do Claude esgotada ({len(candidates)} achados ficam como 'new' "
                f"e brutos em /findings; use /report depois para retomar)."
            )
            return

        await progress(f"Enviando {len(candidates)} achados para triagem do Claude...")
        try:
            result = await claude_invoke.triage(self.settings, job_id, target, candidates)
        except ClaudeInvocationError as e:
            await audit_log("system", "claude:triage_failed", target=target, job_id=job_id, error=str(e))
            await progress(f"Triagem do Claude falhou ({e}) — achados brutos disponiveis em /findings.")
            return

        by_id = {c["id"]: c for c in candidates}
        for item in result.get("findings", []):
            fid = item.get("id")
            verdict = item.get("verdict")
            if fid in by_id and verdict in _VERDICT_TO_STATUS:
                await set_finding_status(fid, _VERDICT_TO_STATUS[verdict])

        await audit_log("system", "claude:triage_done", target=target, job_id=job_id, summary=result.get("summary"))
        await progress(f"Triagem: {result.get('summary', '(sem resumo)')}")
        for action in result.get("next_actions", []):
            await progress(
                f"Claude sugere: {action.get('action')} em {action.get('target', target)} "
                f"— {action.get('reason', '')}"
            )
