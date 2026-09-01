"""Passive subdomain enumeration — first stage of the recon pipeline."""
from __future__ import annotations

import json
from typing import Any

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper


class SubfinderTool(ToolWrapper):
    name = "subfinder"
    # Passive sources without an API key configured are frequently slow to
    # fail/challenge rather than error out fast — give this stage generous
    # headroom; the pipeline treats a timeout here as non-fatal anyway.
    default_timeout = 150

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        rate = max(1, int(scope.rate_limit_rps))
        return [
            tool_path,
            "-d", target,
            "-silent",
            "-oJ",
            "-rl", str(rate),
            "-timeout", "30",
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        seen_hosts: set[str] = set()
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            host = obj.get("host")
            if not host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            findings.append(
                {
                    "finding_type": "subdomain",
                    "severity": "info",
                    "title": f"Subdomain: {host}",
                    "detail": f"source={obj.get('source', 'unknown')}",
                    "url": None,
                    "host": host,  # consumed by the pipeline to feed httpx, not stored in DB
                }
            )
        return findings
