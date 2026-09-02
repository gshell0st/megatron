"""Central configuration: env vars, path resolution, tool discovery.

Never hardcode absolute paths to this repo or to any tool binary elsewhere in
the codebase — everything goes through Settings, resolved once at import time.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# MEGATRON_HOME defaults to the repo root (two levels up from this file),
# but can be overridden by env for portability (e.g. a future AWS install path).
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env")

MEGATRON_HOME = Path(os.environ.get("MEGATRON_HOME", str(_REPO_ROOT))).resolve()
DATA_DIR = MEGATRON_HOME / "data"
LOGS_DIR = DATA_DIR / "logs"
CLAUDE_RAW_LOG_DIR = LOGS_DIR / "claude_raw"
RAW_OUTPUT_DIR = DATA_DIR / "raw"
BACKLOG_DIR = DATA_DIR / "backlog"
DB_PATH = DATA_DIR / "megatron.db"
SCOPE_PATH = MEGATRON_HOME / "scope.yaml"

# tool name -> plausible fallback locations, used only if shutil.which() and
# the TOOL_PATH_<NAME> env override both miss (e.g. snap installs, ~/go/bin).
_FALLBACK_CANDIDATES: dict[str, list[str]] = {
    "subfinder": [str(Path.home() / "go/bin/subfinder")],
    "httpx": ["/snap/bin/httpx"],
    "nuclei": [str(Path.home() / "go/bin/nuclei")],
    "katana": [str(Path.home() / "go/bin/katana")],
    "gau": [str(Path.home() / "go/bin/gau")],
    "ffuf": ["/usr/bin/ffuf"],
    "sqlmap": ["/usr/bin/sqlmap"],
    "dalfox": [str(Path.home() / "go/bin/dalfox")],
    "nmap": ["/usr/bin/nmap"],
    "claude": [str(Path.home() / ".nvm/versions/node/v23.11.0/bin/claude")],
}

# Phase 1 tools the app refuses to boot without.
REQUIRED_TOOLS = ("subfinder", "httpx", "nuclei", "claude")
# Phase 1.5 / Phase 2 tools — resolved if present, missing ones just disable
# the pipelines/commands that need them (checked lazily where used).
OPTIONAL_TOOLS = ("katana", "gau", "ffuf", "sqlmap", "dalfox", "nmap")


def _resolve_tool_path(name: str) -> str | None:
    env_override = os.environ.get(f"TOOL_PATH_{name.upper()}")
    if env_override and Path(env_override).is_file():
        return env_override
    found = shutil.which(name)
    if found:
        return found
    for candidate in _FALLBACK_CANDIDATES.get(name, []):
        if Path(candidate).is_file():
            return candidate
    return None


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    try:
        return float(val) if val is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    discord_application_id: int
    discord_public_key: str | None
    owner_discord_id: int
    guild_id: int
    status_channel_id: int | None

    max_concurrent_jobs: int
    claude_daily_budget: int
    claude_backend: str  # "cli" | "api"
    anthropic_api_key: str | None
    api_call_cost_cap_usd: float
    emergency_stop: bool

    hackerone_api_username: str | None
    hackerone_api_token: str | None
    intigriti_api_token: str | None

    tool_paths: dict[str, str | None] = field(default_factory=dict)

    def tool_path(self, name: str) -> str:
        path = self.tool_paths.get(name)
        if not path:
            raise RuntimeError(
                f"Tool '{name}' is not available (checked env override, PATH, "
                f"and known fallback locations). Set TOOL_PATH_{name.upper()} "
                f"in .env if it's installed somewhere non-standard."
            )
        return path

    def has_tool(self, name: str) -> bool:
        return bool(self.tool_paths.get(name))


def load_settings() -> Settings:
    all_tools = REQUIRED_TOOLS + OPTIONAL_TOOLS
    tool_paths = {name: _resolve_tool_path(name) for name in all_tools}

    missing_required = [t for t in REQUIRED_TOOLS if not tool_paths.get(t)]
    if missing_required:
        raise RuntimeError(
            "Missing required tools, cannot boot: "
            + ", ".join(missing_required)
            + ". Install them or set TOOL_PATH_<NAME> in .env."
        )

    status_channel_raw = os.environ.get("STATUS_CHANNEL_ID", "").strip()

    return Settings(
        discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        discord_application_id=_env_int("DISCORD_APPLICATION_ID", 0),
        discord_public_key=os.environ.get("DISCORD_PUBLIC_KEY") or None,
        owner_discord_id=_env_int("OWNER_DISCORD_ID", 0),
        guild_id=_env_int("GUILD_ID", 0),
        status_channel_id=int(status_channel_raw) if status_channel_raw else None,
        max_concurrent_jobs=_env_int("MEGATRON_MAX_CONCURRENT_JOBS", 1),
        claude_daily_budget=_env_int("MEGATRON_CLAUDE_DAILY_BUDGET", 20),
        claude_backend=os.environ.get("MEGATRON_CLAUDE_BACKEND", "cli"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        api_call_cost_cap_usd=_env_float("MEGATRON_API_CALL_COST_CAP_USD", 1.0),
        emergency_stop=_env_bool("MEGATRON_EMERGENCY_STOP", False),
        hackerone_api_username=os.environ.get("HACKERONE_API_USERNAME") or None,
        hackerone_api_token=os.environ.get("HACKERONE_API_TOKEN") or None,
        intigriti_api_token=os.environ.get("INTIGRITI_API_TOKEN") or None,
        tool_paths=tool_paths,
    )


def ensure_data_dirs() -> None:
    for d in (DATA_DIR, LOGS_DIR, CLAUDE_RAW_LOG_DIR, RAW_OUTPUT_DIR, BACKLOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
