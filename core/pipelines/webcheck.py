"""Web-hygiene pipeline: the 11 check categories the operator asked for
(exposed .env/secrets, exposed .git, exposed backups/config, Swagger/OpenAPI,
GraphQL introspection, actuator/debug endpoints, directory listing, missing
security headers, cookie flags, insecure TLS, and interesting discovered
endpoints), run in one job so Claude's triage step sees a single, already
deduplicated/scored batch instead of having to piece it together itself.

Stage 1 (core/checks/webcheck.py) is pure aiohttp — cheap, always runs.
Stage 2 conditionally runs git-dumper only if stage 1 actually confirmed an
exposed .git (never blind). Stage 3/4 (sslyze, katana) are independent
subprocess tools and always run if installed; a missing optional tool just
skips its stage with a progress note, same pattern as the rest of the app.
Requires mode=active — enforced by core/jobs/queue.py before this ever runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.checks.webcheck import run_web_checks
from core.config import Settings
from core.findings.dedup import upsert_finding
from core.jobs.runner import ToolTimeoutError
from core.scope.loader import ScopeEntry
from core.tools.git_dumper import GitDumperTool
from core.tools.katana import KatanaTool
from core.tools.tls_scan import TlsScanTool

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass
class WebCheckSummary:
    new_count: int = 0
    total_count: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    stages: dict[str, int] = field(default_factory=dict)


async def _ingest(
    findings: list[dict[str, Any]], tool: str, target: str, job_id: int, summary: WebCheckSummary
) -> None:
    for f in findings:
        _, is_new = await upsert_finding(job_id, target, tool, f)
        summary.total_count += 1
        if is_new:
            summary.new_count += 1
        sev = (f.get("severity") or "info").lower()
        summary.by_severity[sev] = summary.by_severity.get(sev, 0) + 1


async def run_webcheck_pipeline(
    settings: Settings,
    target: str,
    scope: ScopeEntry,
    job_id: int,
    progress_cb: ProgressCallback | None = None,
) -> WebCheckSummary:
    async def notify(msg: str) -> None:
        if progress_cb:
            await progress_cb(msg)

    summary = WebCheckSummary()

    await notify(
        "webcheck: headers, cookies, directory listing, .git/.env/backup/swagger/"
        "actuator/graphql em " + target + "..."
    )
    http_findings, git_confirmed = await run_web_checks(target, scope)
    await _ingest(http_findings, "webcheck", target, job_id, summary)
    summary.stages["webcheck"] = len(http_findings)
    await notify(f"webcheck: {len(http_findings)} achado(s).")

    if git_confirmed:
        if settings.has_tool("git-dumper"):
            await notify("git-dumper: .git confirmado exposto, reconstruindo repositorio...")
            try:
                dump_findings = await GitDumperTool().run(settings, target, scope, job_id)
                await _ingest(dump_findings, "git-dumper", target, job_id, summary)
                summary.stages["git-dumper"] = len(dump_findings)
                await notify(f"git-dumper: {len(dump_findings)} achado(s).")
            except ToolTimeoutError:
                summary.stages["git-dumper"] = 0
                await notify("git-dumper: timeout — dump parcial ou nao concluido.")
        else:
            await notify("git-dumper: nao instalado, pulando reconstrucao do repositorio (achado de exposicao ja registrado).")

    if settings.has_tool("sslyze"):
        await notify("sslyze: checando protocolos/cifras/certificado TLS...")
        try:
            tls_findings = await TlsScanTool().run(settings, target, scope, job_id)
            await _ingest(tls_findings, "sslyze", target, job_id, summary)
            summary.stages["sslyze"] = len(tls_findings)
            await notify(f"sslyze: {len(tls_findings)} achado(s).")
        except ToolTimeoutError:
            summary.stages["sslyze"] = 0
            await notify("sslyze: timeout — sem achados desta etapa.")
    else:
        await notify("sslyze: nao instalado, pulando checagem de TLS.")

    if settings.has_tool("katana"):
        await notify("katana: mapeando endpoints interessantes...")
        try:
            crawl_findings = await KatanaTool().run(settings, target, scope, job_id)
            await _ingest(crawl_findings, "katana", target, job_id, summary)
            summary.stages["katana"] = len(crawl_findings)
            await notify(f"katana: {len(crawl_findings)} endpoint(s) interessante(s).")
        except ToolTimeoutError:
            summary.stages["katana"] = 0
            await notify("katana: timeout — sem achados desta etapa.")
    else:
        await notify("katana: nao instalado, pulando descoberta de endpoints.")

    return summary
