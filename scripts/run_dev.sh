#!/usr/bin/env bash
# Quick 24/7-ish launcher for local WSL testing: runs megatron inside a
# detached tmux session so it survives closing the terminal.
#
#   scripts/run_dev.sh start    # launch (or no-op if already running)
#   scripts/run_dev.sh attach   # attach to watch live logs
#   scripts/run_dev.sh stop     # kill the session
#
# For something closer to production (auto-restart on crash), see
# scripts/megatron.service and README.md instead.
set -euo pipefail

SESSION="megatron"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-start}" in
  start)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "Session '$SESSION' already running. Use 'attach' to view it."
    else
      tmux new-session -d -s "$SESSION" -c "$ROOT_DIR" \
        "$ROOT_DIR/.venv/bin/python $ROOT_DIR/megatron run"
      echo "Started tmux session '$SESSION'."
    fi
    ;;
  attach)
    tmux attach -t "$SESSION"
    ;;
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null || echo "Session not running."
    ;;
  *)
    echo "Usage: $0 {start|attach|stop}" >&2
    exit 1
    ;;
esac
