"""Reconstructs an exposed .git repository via git-dumper (pip package
`git-dumper`), only ever invoked by core/pipelines/webcheck.py after its own
check confirms /.git/HEAD or /.git/config is genuinely exposed (see
core/checks/webcheck.py) — this wrapper never probes on its own. Turning a
"200 on .git/config" signal into an actually-reconstructed source tree is
the difference between a guess and demonstrated impact for a report.
Requires mode=active (enforced by core/jobs/queue.py for any non-recon job).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.config import RAW_OUTPUT_DIR
from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

# Filenames a dumped tree gets flagged for — these are exactly the kind of
# "now we have concrete impact" evidence a report needs, not just "a repo
# was exposed."
_INTERESTING_FILENAMES = (
    ".env", "config.php", "wp-config.php", "settings.py", "credentials",
    "id_rsa", ".aws", "secrets.yml", "secrets.yaml", "database.yml",
)


class GitDumperTool(ToolWrapper):
    name = "git-dumper"
    default_timeout = 240

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        url = target if target.startswith("http") else f"https://{target}"
        if not url.rstrip("/").endswith(".git"):
            url = url.rstrip("/") + "/.git"
        dump_dir = RAW_OUTPUT_DIR / str(job_id) / "gitdump"
        dump_dir.mkdir(parents=True, exist_ok=True)
        self._dump_dir = dump_dir  # read back in parse_output — see base.ToolWrapper docstring
        self._target = target
        return [tool_path, url, str(dump_dir)]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        dump_dir: Path = getattr(self, "_dump_dir", None)
        if dump_dir is None or not dump_dir.is_dir():
            return []

        all_files: list[str] = []
        interesting: list[str] = []
        for root, _dirs, files in os.walk(dump_dir):
            for fname in files:
                rel = str(Path(root, fname).relative_to(dump_dir))
                all_files.append(rel)
                if fname.lower() in _INTERESTING_FILENAMES or fname.lower().endswith((".env", ".pem", ".key")):
                    interesting.append(rel)

        if not all_files:
            return []

        detail = f"{len(all_files)} arquivo(s) reconstruido(s) em {dump_dir}"
        if interesting:
            detail += f"; sensiveis: {', '.join(interesting[:10])}"

        return [
            {
                "finding_type": "exposure",
                "severity": "critical" if interesting else "high",
                "title": f"Codigo-fonte reconstruido via .git exposto: {getattr(self, '_target', '')}",
                "detail": detail[:500],
                "url": None,
            }
        ]
