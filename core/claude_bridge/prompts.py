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
                    "note": {"type": "string"},
                },
                "required": ["id", "verdict", "priority"],
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

For each finding, classify it as true-positive-likely, needs-manual-verification, or \
likely-noise, and give it a priority from 1 (ignore) to 5 (investigate now).

Recommend at most 3 next actions, using ONLY the fixed action vocabulary provided by \
the schema. Never recommend destructive, out-of-scope, or high-volume/aggressive actions \
— this operation is intentionally conservative and rate-limited. If nothing stands out, \
return an empty next_actions list.

Respond with JSON matching the provided schema only — no prose outside the JSON."""

_REPORT_INSTRUCTIONS = """You are writing a concise written report for the operator, \
summarizing unreviewed bug-bounty findings against an authorized target. Group related \
findings, call out anything that looks like a real exposure worth manual follow-up, and \
be explicit about uncertainty. Keep it readable in a Discord message (short paragraphs, \
no more than ~300 words). Respond with JSON matching the provided schema only."""


def build_triage_prompt(job_id: int, target: str, findings: list[dict[str, Any]]) -> str:
    payload = {
        "job_id": job_id,
        "target": target,
        "findings": [_truncate_finding(f) for f in findings],
    }
    return f"{_TRIAGE_INSTRUCTIONS}\n\nDATA:\n{json.dumps(payload, default=str)}"


def build_report_prompt(target: str, findings: list[dict[str, Any]]) -> str:
    payload = {"target": target, "findings": [_truncate_finding(f) for f in findings]}
    return f"{_REPORT_INSTRUCTIONS}\n\nDATA:\n{json.dumps(payload, default=str)}"


def _truncate_finding(f: dict[str, Any], detail_max: int = 300) -> dict[str, Any]:
    out = dict(f)
    if out.get("detail") and len(out["detail"]) > detail_max:
        out["detail"] = out["detail"][:detail_max] + "...(truncado)"
    return out
