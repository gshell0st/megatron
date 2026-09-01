"""Phase 1 recon pipeline: subfinder -> httpx -> nuclei.

Each stage's raw findings are deduped/upserted into SQLite as they're
produced; only the fields tool wrappers need for chaining (a bare 'host'
key) are stripped before storage. This is the only place that decides what
counts as "new" for a job, which is what claude_bridge uses to decide
whether a triage call is warranted at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.config import Settings
from core.findings.dedup import upsert_finding
from core.jobs.runner import ToolTimeoutError
from core.scope.loader import ScopeEntry
from core.tools.httpx_tool import HttpxTool
from core.tools.nuclei import NucleiTool
from core.tools.subfinder import SubfinderTool

ProgressCallback = Callable[[str], Awaitable[None]]

# Passive enumeration against a large/old domain can return thousands of
# hosts (certificate-transparency noise especially). Cap what actually gets
# probed/scanned so one job can't turn into an unbounded, hours-long run —
# conservative by design, matching the "don't be a lot of noise" goal.
MAX_HOSTS_FOR_HTTPX = 300
# Measured directly against a live host with this project's tag set (see
# core/tools/nuclei.py): 439 templates -> 2253 requests after clustering.
# That's the real per-host cost driving nuclei's runtime, not host count
# alone, so MAX_HOSTS_FOR_NUCLEI stays small — 5 hosts at a conservative
# 5 rps is already ~35 minutes.
MAX_HOSTS_FOR_NUCLEI = 5
EST_NUCLEI_REQUESTS_PER_HOST = 2300

_HTTPX_BASE_TIMEOUT = 30.0
_HTTPX_TIMEOUT_CEILING = 600.0
_NUCLEI_BASE_TIMEOUT = 30.0
_NUCLEI_TIMEOUT_CEILING = 2700.0


def _scaled_timeout(base: float, host_count: int, rate_limit_rps: float, ceiling: float) -> float:
    """A rate-limited stage over N hosts legitimately takes longer than the
    same stage over 5 — scale the timeout with the input size instead of
    hardcoding one number that's wrong at both ends of the range. Factor is
    generous (2x the naive rate-limit estimate) because unresponsive/dead
    hosts (common in passive-enum output) each burn their full per-request
    timeout rather than completing instantly like a live host would."""
    estimate = base + (host_count / max(rate_limit_rps, 1.0)) * 2.0
    return min(ceiling, estimate)


def _nuclei_timeout(host_count: int, rate_limit_rps: float) -> float:
    """Scale by measured requests/host rather than host count alone —
    nuclei's cost here is dominated by template count, not target count."""
    estimate = _NUCLEI_BASE_TIMEOUT + (
        host_count * EST_NUCLEI_REQUESTS_PER_HOST / max(rate_limit_rps, 1.0)
    ) * 1.1
    return min(_NUCLEI_TIMEOUT_CEILING, estimate)


@dataclass
class PipelineSummary:
    new_count: int = 0
    total_count: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    stages: dict[str, int] = field(default_factory=dict)


async def _ingest(
    findings: list[dict[str, Any]],
    tool: str,
    target: str,
    job_id: int,
    summary: PipelineSummary,
) -> list[str]:
    """Upserts every finding, returns the 'host' chain-values (if present)
    for feeding into the next stage."""
    hosts: list[str] = []
    for f in findings:
        host = f.pop("host", None)
        if host:
            hosts.append(host)
        _, is_new = await upsert_finding(job_id, target, tool, f)
        summary.total_count += 1
        if is_new:
            summary.new_count += 1
        sev = (f.get("severity") or "info").lower()
        summary.by_severity[sev] = summary.by_severity.get(sev, 0) + 1
    return hosts


async def run_recon_pipeline(
    settings: Settings,
    target: str,
    scope: ScopeEntry,
    job_id: int,
    progress_cb: ProgressCallback | None = None,
) -> PipelineSummary:
    async def notify(msg: str) -> None:
        if progress_cb:
            await progress_cb(msg)

    summary = PipelineSummary()

    await notify(f"subfinder: enumerando subdominios de `{target}`...")
    try:
        subfinder_findings = await SubfinderTool().run(settings, target, scope, job_id)
        hosts = await _ingest(subfinder_findings, "subfinder", target, job_id, summary)
    except ToolTimeoutError:
        hosts = []
        await notify("subfinder: timeout (fontes passivas lentas/sem API key) — seguindo so com o dominio raiz.")
    if target not in hosts:
        hosts.append(target)
    summary.stages["subfinder"] = len(hosts)
    await notify(f"subfinder: {len(hosts)} hosts candidatos.")

    if len(hosts) > MAX_HOSTS_FOR_HTTPX:
        await notify(
            f"subfinder achou {len(hosts)} hosts — limitando httpx aos primeiros "
            f"{MAX_HOSTS_FOR_HTTPX} para manter o job em tempo/carga razoaveis."
        )
        hosts = hosts[:MAX_HOSTS_FOR_HTTPX]

    httpx_timeout = _scaled_timeout(_HTTPX_BASE_TIMEOUT, len(hosts), scope.rate_limit_rps, _HTTPX_TIMEOUT_CEILING)
    await notify(f"httpx: sondando {len(hosts)} hosts (timeout={httpx_timeout:.0f}s)...")
    try:
        httpx_findings = await HttpxTool().run(
            settings, target, scope, job_id, stdin_lines=hosts, timeout_override=httpx_timeout
        )
        live_urls = await _ingest(httpx_findings, "httpx", target, job_id, summary)
    except ToolTimeoutError:
        live_urls = []
        await notify("httpx: timeout — abortando antes do nuclei.")
    summary.stages["httpx"] = len(live_urls)
    await notify(f"httpx: {len(live_urls)} hosts vivos.")

    if not live_urls:
        return summary

    if len(live_urls) > MAX_HOSTS_FOR_NUCLEI:
        await notify(
            f"httpx achou {len(live_urls)} hosts vivos — limitando nuclei aos primeiros "
            f"{MAX_HOSTS_FOR_NUCLEI}."
        )
        live_urls = live_urls[:MAX_HOSTS_FOR_NUCLEI]

    nuclei_timeout = _nuclei_timeout(len(live_urls), scope.rate_limit_rps)
    await notify(
        f"nuclei: checando exposicoes/misconfig em {len(live_urls)} hosts "
        f"(timeout={nuclei_timeout:.0f}s — pode demorar, e um processo em background)..."
    )
    try:
        nuclei_findings = await NucleiTool().run(
            settings, target, scope, job_id, stdin_lines=live_urls, timeout_override=nuclei_timeout
        )
        await _ingest(nuclei_findings, "nuclei", target, job_id, summary)
        summary.stages["nuclei"] = len(nuclei_findings)
        await notify(f"nuclei: {len(nuclei_findings)} achados.")
    except ToolTimeoutError:
        summary.stages["nuclei"] = 0
        await notify("nuclei: timeout — sem achados desta etapa.")

    return summary
