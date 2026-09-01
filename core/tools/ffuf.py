"""Exposed-file/path discovery via ffuf, using a short curated wordlist
(config/sensitive_paths.txt) — not generic brute-force. Requires mode=active
in scope.yaml (enforced by core/jobs/queue.py before this ever runs).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import MEGATRON_HOME, RAW_OUTPUT_DIR
from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

_WORDLIST_PATH = MEGATRON_HOME / "config" / "sensitive_paths.txt"


def _filtered_wordlist(scope: ScopeEntry, job_id: int) -> Path:
    """Write a copy of sensitive_paths.txt with any scope.excluded_paths
    prefixes stripped out — a job's ffuf run can never touch an excluded
    path, regardless of what's in the base wordlist."""
    lines = _WORDLIST_PATH.read_text().splitlines()
    excluded = tuple(p.lstrip("/") for p in scope.excluded_paths)
    kept = [
        line for line in lines
        if line.strip() and not line.strip().startswith("#")
        and not any(line.strip().startswith(prefix) for prefix in excluded)
    ]
    out_path = RAW_OUTPUT_DIR / str(job_id) / "ffuf_wordlist.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(kept) + "\n")
    return out_path


class FfufTool(ToolWrapper):
    name = "ffuf"
    default_timeout = 300

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        wordlist = _filtered_wordlist(scope, job_id)
        rate = max(1, int(scope.rate_limit_rps))
        url = target if target.startswith("http") else f"https://{target}"
        return [
            tool_path,
            "-u", f"{url.rstrip('/')}/FUZZ",
            "-w", str(wordlist),
            "-mc", "200,201,204,301,302,307,401,403",
            "-rate", str(rate),
            "-t", str(min(10, rate * 2)),
            "-timeout", "10",
            "-of", "json",
            "-o", "/dev/stdout",
            "-s",
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        try:
            obj = json.loads(raw_stdout)
        except json.JSONDecodeError:
            return findings
        for result in obj.get("results", []):
            url = result.get("url", "")
            status = result.get("status")
            length = result.get("length")
            findings.append(
                {
                    "finding_type": "exposure",
                    "severity": "medium" if status in (200, 201, 204) else "low",
                    "title": f"Path found: {url} [{status}]",
                    "detail": f"length={length} words={result.get('words')} lines={result.get('lines')}",
                    "url": url,
                }
            )
        return findings
