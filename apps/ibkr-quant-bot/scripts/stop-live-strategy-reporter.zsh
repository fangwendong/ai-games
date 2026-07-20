#!/usr/bin/env zsh
emulate -L zsh
set -uo pipefail

session_name=ibkr-live-strategy-reporter

if tmux has-session -t "$session_name" 2>/dev/null; then
  tmux kill-session -t "$session_name"
fi
