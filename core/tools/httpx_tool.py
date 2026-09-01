"""Live-host probing — second stage of the recon pipeline. Reads hostnames
from stdin (fed by the subfinder stage), never takes a raw target argument,
so it can only ever probe hosts the pipeline itself discovered.
"""
from __future__ import annotations

import json
from typing import Any

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper


class HttpxTool(ToolWrapper):
    name = "httpx"
    default_timeout = 180

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry) -> list[str]:
        rate = max(1, int(scope.rate_limit_rps))
        return [
            tool_path,
            "-json",
            "-silent",
            "-rl", str(rate),
            "-timeout", "10",
            "-retries", "0",  # predictable worst-case duration matters more here than catching flaky hosts
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = obj.get("url")
            if not url:
                continue
            title = obj.get("title", "")
            status = obj.get("status-code")
            webserver = obj.get("webserver", "")
            findings.append(
                {
                    "finding_type": "live-host",
                    "severity": "info",
                    "title": f"Live host: {url} [{status}]",
                    "detail": f"title={title!r} webserver={webserver!r}",
                    "url": url,
                    "host": url,  # consumed by the pipeline to feed nuclei, not stored in DB
                }
            )
        return findings
