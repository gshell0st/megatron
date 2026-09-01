"""Conservative sqlmap wrapper against a single URL with a query string.

sqlmap has no clean structured-output mode, so parsing its stdout report is
best-effort regex — the full raw stdout is always saved to
data/raw/<job_id>/sqlmap.out (via ToolWrapper.run) as the ground truth for
manual review regardless of what the parser catches.

--technique=BEUQ deliberately excludes S (stacked queries — can execute
arbitrary extra statements) and T (time-based blind — slow/noisy); risk=1
level=1 keep payloads to the least invasive tests. Requires mode=active.
"""
from __future__ import annotations

import re
from typing import Any

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

_PARAM_BLOCK_RE = re.compile(
    r"Parameter:\s*(?P<param>\S+)\s*\((?P<place>[^)]+)\)\s*\n"
    r"\s*Type:\s*(?P<type>.+?)\s*\n"
    r"\s*Title:\s*(?P<title>.+?)\s*\n",
    re.MULTILINE,
)
_DBMS_RE = re.compile(r"back-end DBMS:\s*(?P<dbms>.+)")


class SqlmapTool(ToolWrapper):
    name = "sqlmap"
    default_timeout = 600

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        return [
            tool_path,
            "-u", target,
            "--batch",
            "--risk=1",
            "--level=1",
            "--technique=BEUQ",
            "--threads=1",
            "-v", "1",
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        dbms_match = _DBMS_RE.search(raw_stdout)
        dbms = dbms_match.group("dbms").strip() if dbms_match else None

        for match in _PARAM_BLOCK_RE.finditer(raw_stdout):
            findings.append(
                {
                    "finding_type": "vuln",
                    "severity": "critical",
                    "title": f"Possible SQLi: param '{match['param']}' ({match['place']})",
                    "detail": f"type={match['type']} title={match['title']} dbms={dbms or 'unknown'}",
                    "url": None,
                }
            )
        return findings
