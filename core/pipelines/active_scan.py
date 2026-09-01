"""Phase 2 active-scan pipeline: dispatches to ffuf/dalfox/sqlmap depending
on job_type, mirroring core/pipelines/recon.py's shape (ingest via
upsert_finding, report a summary, let ToolTimeoutError degrade gracefully).
Only reachable for scope entries with mode=active (enforced in
core/jobs/queue.py before this is called).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.config import Settings
from core.findings.dedup import upsert_finding
from core.jobs.runner import ToolTimeoutError
from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper
from core.tools.dalfox import DalfoxTool
from core.tools.ffuf import FfufTool
from core.tools.sqlmap import SqlmapTool

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass
class ActiveScanSummary:
    new_count: int = 0
    total_count: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)


async def _ingest(
    findings: list[dict[str, Any]], tool: str, target: str, job_id: int, summary: ActiveScanSummary
) -> None:
    for f in findings:
        f.pop("host", None)
        _, is_new = await upsert_finding(job_id, target, tool, f)
        summary.total_count += 1
        if is_new:
            summary.new_count += 1
        sev = (f.get("severity") or "info").lower()
        summary.by_severity[sev] = summary.by_severity.get(sev, 0) + 1


def _resolve(job_type: str, target: str, params: dict[str, Any]) -> tuple[ToolWrapper, str]:
    if job_type == "ffuf":
        return FfufTool(), target
    if job_type == "xss":
        url = params.get("url")
        if not url:
            raise ValueError("xss job requires params['url']")
        return DalfoxTool(), url
    if job_type == "sqli":
        url = params.get("url")
        if not url:
            raise ValueError("sqli job requires params['url']")
        return SqlmapTool(), url
    raise ValueError(f"unknown active scan job_type: {job_type}")


async def run_active_scan_pipeline(
    settings: Settings,
    job_type: str,
    target: str,
    scope: ScopeEntry,
    job_id: int,
    params: dict[str, Any],
    progress_cb: ProgressCallback | None = None,
) -> ActiveScanSummary:
    async def notify(msg: str) -> None:
        if progress_cb:
            await progress_cb(msg)

    summary = ActiveScanSummary()
    tool, tool_target = _resolve(job_type, target, params)

    await notify(f"{tool.name}: iniciando contra `{tool_target}`...")
    try:
        findings = await tool.run(settings, tool_target, scope, job_id)
        await _ingest(findings, tool.name, target, job_id, summary)
        await notify(f"{tool.name}: {len(findings)} achados.")
    except ToolTimeoutError:
        await notify(f"{tool.name}: timeout — sem achados desta etapa.")

    return summary
