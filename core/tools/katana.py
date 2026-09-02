"""Endpoint discovery via katana, scoped to a single fqdn and capped in
depth/duration to stay a "light crawl" rather than a full-site mirror.
parse_output scores every discovered endpoint and only keeps the ones worth
a human's/Claude's attention (query params, admin/debug-sounding paths,
common API/file-upload patterns) — a raw crawl can return hundreds of
boring URLs, and storing all of them would be exactly the kind of grunt
work Claude shouldn't have to wade through. Requires mode=active.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

_MAX_STORED_ENDPOINTS = 40
_MIN_SCORE_TO_KEEP = 2

_INTERESTING_KEYWORDS = (
    "admin", "internal", "staging", "debug", "console", "manage", "backup",
    "export", "import", "upload", "download", "config", "secret", "token",
    "key", "password", "reset", "delete", "impersonate", "account", "user",
    "api", "v1", "v2", "v3", "graphql", "wp-json", "actuator",
)
_HIGH_WEIGHT_KEYWORDS = ("admin", "internal", "debug", "delete", "backup", "secret", "impersonate")


def _score(endpoint: str) -> int:
    parsed = urlsplit(endpoint)
    path_and_query = f"{parsed.path.lower()}?{parsed.query.lower()}"
    score = 0
    if parsed.query:
        score += 1
    for kw in _INTERESTING_KEYWORDS:
        if kw in path_and_query:
            score += 2 if kw in _HIGH_WEIGHT_KEYWORDS else 1
    return score


class KatanaTool(ToolWrapper):
    name = "katana"
    default_timeout = 240

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        url = target if target.startswith("http") else f"https://{target}"
        rate = max(1, int(scope.rate_limit_rps))
        return [
            tool_path,
            "-u", url,
            "-jsonl",
            "-silent",
            "-fs", "fqdn",
            "-d", "2",
            "-rl", str(rate),
            "-ct", "180s",
            "-or",  # omit-raw
            "-ob",  # omit-body
        ]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        scored: list[tuple[int, str, int | None]] = []
        seen: set[str] = set()
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            endpoint = (obj.get("request") or {}).get("endpoint")
            if not endpoint or endpoint in seen:
                continue
            seen.add(endpoint)
            status = (obj.get("response") or {}).get("status_code")
            score = _score(endpoint)
            if score >= _MIN_SCORE_TO_KEEP:
                scored.append((score, endpoint, status))

        scored.sort(key=lambda t: t[0], reverse=True)
        findings: list[dict[str, Any]] = []
        for score, endpoint, status in scored[:_MAX_STORED_ENDPOINTS]:
            findings.append(
                {
                    "finding_type": "endpoint",
                    "severity": "medium" if score >= 4 else "low",
                    "title": f"Endpoint interessante: {endpoint}",
                    "detail": f"score={score} status={status}",
                    "url": endpoint,
                }
            )
        return findings
