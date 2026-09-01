"""Light XSS scanning via dalfox against a single, already-parameterized URL
— the caller (core/pipelines/active_scan.py) is responsible for requiring a
URL with a query string; this wrapper never crawls/mines beyond it
(--skip-mining-all) to stay conservative. Requires mode=active in scope.yaml.
"""
from __future__ import annotations

import json
from typing import Any

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper


class DalfoxTool(ToolWrapper):
    name = "dalfox"
    default_timeout = 300

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        worker = max(1, min(10, int(scope.rate_limit_rps) * 2))
        return [
            tool_path,
            "url", target,
            "--format", "json",
            "--worker", str(worker),
            "--skip-mining-all",
            "--skip-bav",
            "--delay", "300",
            "--timeout", "10",
            "--no-color",
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        text = raw_stdout.strip()
        if not text:
            return findings

        items: list[dict[str, Any]] = []
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else parsed.get("results", [parsed])
        except json.JSONDecodeError:
            # dalfox sometimes emits one JSON object per line rather than a
            # single array — fall back to jsonl parsing before giving up.
            for line in text.splitlines():
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        for item in items:
            if not isinstance(item, dict):
                continue
            param = item.get("param", "?")
            url = item.get("url") or item.get("data", "")
            findings.append(
                {
                    "finding_type": "vuln",
                    "severity": "high",
                    "title": f"Possible XSS via param '{param}'",
                    "detail": json.dumps(item, default=str)[:500],
                    "url": url,
                }
            )
        return findings
