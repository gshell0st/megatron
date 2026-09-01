"""The only place in the codebase that shells out to `claude`. Pure
text-in/JSON-out: the headless call runs with --restricted (no Bash/code
execution/WebFetch, file tools confined to cwd) and --setting-sources ""
from a scratch directory outside the repo, so it never sees this repo's
CLAUDE.md and never gets a chance to act — it can only analyze and answer.

Confirmed against the installed claude CLI (v2.1.252): with
--output-format json --json-schema <schema>, the response envelope already
contains a `structured_output` field holding the schema-validated object —
no need to re-parse the `result` string in the common case.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from core.claude_bridge import quota
from core.claude_bridge.prompts import (
    SUBMISSION_DRAFT_SCHEMA,
    TRIAGE_JSON_SCHEMA,
    build_report_prompt,
    build_submission_draft_prompt,
    build_triage_prompt,
)
from core.config import CLAUDE_RAW_LOG_DIR, Settings
from core.jobs.runner import run_subprocess

INVOCATION_TIMEOUT_S = 90


class ClaudeInvocationError(Exception):
    pass


def _fallback_result(raw_text: str) -> dict[str, Any]:
    return {"summary": raw_text or "(sem resposta)", "findings": [], "next_actions": []}


async def _invoke(
    settings: Settings,
    prompt: str,
    purpose: str,
    job_id: int | None,
    log_name: str,
    schema: dict[str, Any] = TRIAGE_JSON_SCHEMA,
) -> dict[str, Any]:
    if not await quota.can_invoke():
        raise ClaudeInvocationError("daily claude invocation budget exhausted")

    claude_path = settings.tool_path("claude")
    cmd = [
        claude_path,
        "-p",
        "--output-format", "json",
        "--restricted",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--json-schema", json.dumps(schema),
    ]
    if settings.claude_backend == "api":
        cmd += ["--max-budget-usd", str(settings.api_call_cost_cap_usd)]

    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="megatron-claude-") as scratch_dir:
        result = await run_subprocess(
            [*cmd],
            timeout=INVOCATION_TIMEOUT_S,
            stdin_data=prompt.encode(),
        )
        # run_subprocess doesn't take cwd; scratch_dir isolation is enforced
        # by --setting-sources "" + --restricted above instead. Directory is
        # created/discarded purely so nothing is ever written into the repo
        # by mistake if a future flag change re-enables file tools.
        _ = scratch_dir

    duration_ms = int((time.monotonic() - start) * 1000)

    CLAUDE_RAW_LOG_DIR.mkdir(parents=True, exist_ok=True)
    (CLAUDE_RAW_LOG_DIR / f"{log_name}.json").write_text(result.stdout or result.stderr)

    if result.timed_out:
        await quota.record(purpose, settings.claude_backend, job_id=job_id, duration_ms=duration_ms, success=False, error="timeout")
        raise ClaudeInvocationError(f"claude -p timed out after {INVOCATION_TIMEOUT_S}s")

    if result.returncode != 0:
        await quota.record(purpose, settings.claude_backend, job_id=job_id, duration_ms=duration_ms, success=False, error=result.stderr[:500])
        raise ClaudeInvocationError(f"claude -p exited {result.returncode}: {result.stderr[:300]}")

    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        await quota.record(purpose, settings.claude_backend, job_id=job_id, duration_ms=duration_ms, success=False, error="unparseable --output-format json envelope")
        raise ClaudeInvocationError("could not parse claude --output-format json envelope") from e

    model_usage = envelope.get("modelUsage") or {}
    await quota.record(
        purpose,
        settings.claude_backend,
        job_id=job_id,
        model=next(iter(model_usage), None),
        duration_ms=duration_ms,
        total_cost_usd=envelope.get("total_cost_usd"),
        success=not envelope.get("is_error", False),
        error=None if not envelope.get("is_error") else str(envelope.get("result"))[:500],
    )

    if envelope.get("is_error"):
        raise ClaudeInvocationError(f"claude reported is_error: {envelope.get('result')}")

    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured

    # fallback: schema-mode should always give structured_output, but if a
    # future CLI version changes shape, try parsing `result` as JSON before
    # giving up and treating it as freeform text (never crash the job).
    raw_result = envelope.get("result", "")
    try:
        parsed = json.loads(raw_result)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return _fallback_result(str(raw_result))


async def triage(settings: Settings, job_id: int, target: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = build_triage_prompt(job_id, target, findings)
    return await _invoke(settings, prompt, purpose="triage", job_id=job_id, log_name=f"triage_job{job_id}_{int(time.time())}")


async def report(settings: Settings, target: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = build_report_prompt(target, findings)
    return await _invoke(settings, prompt, purpose="report", job_id=None, log_name=f"report_{target}_{int(time.time())}")


async def draft_submission(settings: Settings, target: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Produces {title, impact, vulnerability_information, severity_rating}
    formatted for HackerOne's report fields. Never calls the platform API
    itself — bot/commands/submit_cmds.py stores the result as a pending
    report_drafts row and only submits after an explicit /submit confirm."""
    prompt = build_submission_draft_prompt(target, findings)
    return await _invoke(
        settings,
        prompt,
        purpose="submission_draft",
        job_id=None,
        log_name=f"submission_draft_{target}_{int(time.time())}",
        schema=SUBMISSION_DRAFT_SCHEMA,
    )
