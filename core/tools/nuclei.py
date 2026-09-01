"""Exposure / misconfiguration scanning — third stage of the recon
pipeline. Reads live-host URLs from stdin (fed by the httpx stage). Tags
are fixed to exposure/misconfig-oriented templates; dos/fuzz/intrusive are
always excluded regardless of what a future command surface might request.
"""
from __future__ import annotations

import json
from typing import Any

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

# default-login (router/IoT/device creds) is deliberately excluded: it's the
# single largest template category here and isn't central to the "exposed
# files/APIs" use case this tool targets — dropping it keeps per-host
# runtime much more bounded for the same reason dos/fuzz/intrusive are out.
INCLUDE_TAGS = "exposures,misconfiguration,config,backup,exposed-panel,token"
EXCLUDE_TAGS = "dos,fuzz,intrusive,default-login"


class NucleiTool(ToolWrapper):
    name = "nuclei"
    default_timeout = 300

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        rate = max(1, int(scope.rate_limit_rps))
        return [
            tool_path,
            "-jsonl",
            "-silent",
            "-tags", INCLUDE_TAGS,
            "-etags", EXCLUDE_TAGS,
            "-rl", str(rate),
            "-timeout", "10",
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
            info = obj.get("info", {}) or {}
            host = obj.get("host") or obj.get("matched-at", "")
            name = info.get("name", obj.get("template-id", "unknown finding"))
            severity = (info.get("severity") or "info").lower()
            findings.append(
                {
                    "finding_type": "exposure",
                    "severity": severity,
                    "title": f"{name} @ {host}",
                    "detail": json.dumps(
                        {
                            "template-id": obj.get("template-id"),
                            "matched-at": obj.get("matched-at"),
                            "extracted-results": obj.get("extracted-results"),
                        },
                        default=str,
                    )[:500],
                    "url": obj.get("matched-at") or host,
                }
            )
        return findings
