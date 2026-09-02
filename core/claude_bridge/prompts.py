"""Static prompt templates + output schema for headless claude -p calls.

These are the entire "system prompt" for the runtime brain — deliberately
NOT sourced from the repo's CLAUDE.md (that file is for the human's
interactive dev sessions only). Treat changes here like any other code
change: reviewed, versioned, tested.
"""
from __future__ import annotations

import json
from typing import Any

TRIAGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "true-positive-likely",
                            "needs-manual-verification",
                            "likely-noise",
                        ],
                    },
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "impact": {
                        "type": "string",
                        "description": "Concrete real-world impact if exploited — what an attacker actually gains, not just the technical defect.",
                    },
                    "note": {"type": "string"},
                },
                "required": ["id", "verdict", "priority", "impact"],
            },
        },
        "next_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "recon",
                            "xss-scan",
                            "sqli-scan",
                            "ffuf-scan",
                            "manual-review",
                            "none",
                        ],
                    },
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "reason"],
            },
        },
    },
    "required": ["summary", "findings", "next_actions"],
}

_TRIAGE_INSTRUCTIONS = """You are a bug-bounty triage analyst reviewing automated recon/scan output \
against a target the operator has EXPLICITLY AUTHORIZED for testing (verified by a \
separate scope-enforcement system before this data ever reached you).

IMPACT IS THE TOP PRIORITY HERE — above any individual vulnerability class, tool severity \
label, or raw finding count. For every finding, first reason concretely about what an \
attacker could ACTUALLY achieve if it's real: data exposure, credential/secret leakage, \
account takeover, lateral movement, business/financial harm. A single finding with clear, \
demonstrated impact matters more than a long list of low-impact or theoretical findings. \
Where two or more findings could be chained into a bigger real-world consequence (e.g. an \
exposed config file that leaks a credential usable elsewhere), say so explicitly — that \
chained story is more valuable than either finding alone. Deprioritize anything that is \
technically valid but has no plausible real-world impact path, even if its raw severity \
label is high.

For each finding, classify it as true-positive-likely, needs-manual-verification, or \
likely-noise; write a concrete one-sentence "impact" statement (what an attacker actually \
gains — never just restate the technical defect); and give it a priority from 1 (ignore) \
to 5 (investigate now) driven primarily by that impact, not by the tool's severity label.

Recommend at most 3 next actions, using ONLY the fixed action vocabulary provided by \
the schema. Never recommend destructive, out-of-scope, or high-volume/aggressive actions \
— this operation is intentionally conservative and rate-limited. If nothing stands out, \
return an empty next_actions list.

If a "history" block is present in the DATA, this target has been tested before: use it as \
grounding, not as a rulebook. "related_past_verdicts" shows how similar findings on this same \
target were previously judged — weigh new findings against that precedent, but don't just \
copy an old verdict; a superficially similar finding can have a different concrete impact. \
"not_redetected_since_last_scan" lists findings that existed last scan but weren't seen \
again — call these out in next_actions (e.g. manual-review) only if a plausible fix or \
significant impact is at stake, since most disappear for mundane reasons (host down, rate \
limiting). Silence about history in your summary is fine when there's nothing notable in it.

Respond with JSON matching the provided schema only — no prose outside the JSON."""

_REPORT_INSTRUCTIONS = """You are writing a concise written report for the operator, \
summarizing unreviewed bug-bounty findings against an authorized target.

IMPACT IS THE TOP PRIORITY HERE — above any individual vulnerability class, tool severity \
label, or raw finding count. Lead with what an attacker could actually achieve, not with a \
flat list of technical defects. Group related findings and, where they chain into a bigger \
real-world consequence, tell that story explicitly rather than listing them separately. Be \
explicit about uncertainty (soft-404s, unconfirmed responses) so low-confidence findings \
don't get overstated. Keep it readable in a Discord message (short paragraphs, no more than \
~300 words).

For each finding included, write a concrete one-sentence "impact" statement (what an \
attacker actually gains) and a priority from 1-5 driven by that impact. Respond with JSON \
matching the provided schema only."""


SUBMISSION_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "impact": {"type": "string"},
        "vulnerability_information": {"type": "string"},
        "severity_rating": {
            "type": "string",
            "enum": ["none", "low", "medium", "high", "critical"],
        },
    },
    "required": ["title", "impact", "vulnerability_information", "severity_rating"],
}

_SUBMISSION_DRAFT_INSTRUCTIONS = """You are drafting a HackerOne vulnerability report on \
behalf of the operator, from findings that have ALREADY been triaged as true-positive-likely \
against an authorized target.

IMPACT IS THE TOP PRIORITY — lead the report with concrete real-world impact (what an \
attacker actually gains), not a dry technical description. If multiple findings are \
provided, weave them into a single coherent report only if they genuinely share a root \
cause or chain into one bigger impact story; otherwise draft around the single \
highest-impact finding and mention the others only briefly as secondary/related.

Write:
- title: short, specific, impact-oriented — not just the vulnerability class name.
- impact: 2-4 sentences on concrete real-world consequence if exploited.
- vulnerability_information: clear, numbered steps to reproduce (using the URLs/params/\
details given), written for a program triager who has no other context.
- severity_rating: none/low/medium/high/critical, judged by real impact — not by whatever \
raw severity label the scanning tool assigned.

Respond with JSON matching the provided schema only — no prose outside the JSON."""


def build_submission_draft_prompt(target: str, findings: list[dict[str, Any]]) -> str:
    payload = {"target": target, "findings": [_truncate_finding(f) for f in findings]}
    return f"{_SUBMISSION_DRAFT_INSTRUCTIONS}\n\nDATA:\n{json.dumps(payload, default=str)}"


def build_triage_prompt(
    job_id: int,
    target: str,
    findings: list[dict[str, Any]],
    history_context: dict[str, Any] | None = None,
) -> str:
    payload = {
        "job_id": job_id,
        "target": target,
        "findings": [_truncate_finding(f) for f in findings],
    }
    if history_context is not None:
        payload["history"] = history_context
    return f"{_TRIAGE_INSTRUCTIONS}\n\nDATA:\n{json.dumps(payload, default=str)}"


def build_report_prompt(target: str, findings: list[dict[str, Any]]) -> str:
    payload = {"target": target, "findings": [_truncate_finding(f) for f in findings]}
    return f"{_REPORT_INSTRUCTIONS}\n\nDATA:\n{json.dumps(payload, default=str)}"


def _truncate_finding(f: dict[str, Any], detail_max: int = 300) -> dict[str, Any]:
    out = dict(f)
    if out.get("detail") and len(out["detail"]) > detail_max:
        out["detail"] = out["detail"][:detail_max] + "...(truncado)"
    return out
