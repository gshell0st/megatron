"""Generic async subprocess execution shared by every tool wrapper and by
the claude_bridge. Owns a registry of live processes so /jobs cancel can
kill a real running subprocess, not just flip a DB flag.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Hashable


@dataclass
class SubprocessResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool


class ToolTimeoutError(Exception):
    pass


_live_procs: dict[Hashable, asyncio.subprocess.Process] = {}


def cancel(register_key: Hashable) -> bool:
    """Kill a live subprocess by its registry key, if it's still running."""
    proc = _live_procs.get(register_key)
    if proc is None or proc.returncode is not None:
        return False
    proc.kill()
    return True


def cancel_all_for_job(job_id: int) -> bool:
    """Kill every live subprocess registered under (job_id, tool_name) keys
    — used by JobQueue.cancel() without it needing to know our key shape."""
    killed_any = False
    for key in list(_live_procs.keys()):
        if isinstance(key, tuple) and key and key[0] == job_id:
            if cancel(key):
                killed_any = True
    return killed_any


async def run_subprocess(
    cmd: list[str],
    timeout: float,
    output_path: Path | None = None,
    register_key: Hashable | None = None,
    stdin_data: bytes | None = None,
) -> SubprocessResult:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if register_key is not None:
        _live_procs[register_key] = proc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_data), timeout=timeout
        )
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout, stderr, timed_out = b"", b"process timed out", True
    finally:
        if register_key is not None:
            _live_procs.pop(register_key, None)

    stdout_text = stdout.decode(errors="replace")
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(stdout_text)

    return SubprocessResult(
        stdout=stdout_text,
        stderr=stderr.decode(errors="replace"),
        returncode=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
    )
