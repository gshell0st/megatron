"""Shared contract every tool wrapper implements: build a conservative
command line for a given (target, scope) pair, run it, and parse its
output into plain dicts ready to become Finding rows.

Rate limits and excluded paths always come from the ScopeEntry the caller
passes in — never from raw Discord input — so a wrapper cannot be made to
scan harder than scope.yaml allows.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.config import RAW_OUTPUT_DIR, Settings
from core.jobs.runner import ToolTimeoutError, run_subprocess
from core.scope.loader import ScopeEntry


class ToolWrapper(ABC):
    name: str
    default_timeout: float = 180

    @abstractmethod
    def build_command(self, tool_path: str, target: str, scope: ScopeEntry) -> list[str]:
        """Return the full argv for this tool, using scope.rate_limit_rps /
        scope.excluded_paths for any throttling/exclusion flags."""

    @abstractmethod
    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        """Return a list of dicts with keys: finding_type, severity, title,
        detail, url (severity/detail/url may be None)."""

    async def run(
        self,
        settings: Settings,
        target: str,
        scope: ScopeEntry,
        job_id: int,
        stdin_lines: list[str] | None = None,
        timeout_override: float | None = None,
    ) -> list[dict[str, Any]]:
        """stdin_lines lets a stage feed the previous stage's output in
        (e.g. subdomains -> httpx, live hosts -> nuclei) via stdin, which is
        how these tools are meant to be chained. timeout_override lets a
        pipeline scale the timeout to the input size (e.g. probing 2000
        hosts at a conservative rate limit legitimately takes longer than
        probing 5) instead of hardcoding one number for every input size."""
        tool_path = settings.tool_path(self.name)
        cmd = self.build_command(tool_path, target, scope)
        output_path = RAW_OUTPUT_DIR / str(job_id) / f"{self.name}.out"
        stdin_data = ("\n".join(stdin_lines) + "\n").encode() if stdin_lines else None
        timeout = timeout_override if timeout_override is not None else self.default_timeout

        result = await run_subprocess(
            cmd,
            timeout=timeout,
            output_path=output_path,
            register_key=(job_id, self.name),
            stdin_data=stdin_data,
        )
        if result.timed_out:
            raise ToolTimeoutError(f"{self.name} timed out after {timeout:.0f}s")
        return self.parse_output(result.stdout)
