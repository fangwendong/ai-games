#!/usr/bin/env zsh
emulate -L zsh
set -uo pipefail

script_dir=${0:A:h}
app_dir=${script_dir:h}
cd "$app_dir"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

session_name=ibkr-live-strategy-reporter
runner="$script_dir/run-live-strategy-report-loop.zsh"

if tmux has-session -t "$session_name" 2>/dev/null; then
  exit 0
fi

: ${BOTMUX_REPORT_SESSION_ID:?BOTMUX_REPORT_SESSION_ID is required}
: ${BOTMUX_REPORT_ROOT_MESSAGE_ID:?BOTMUX_REPORT_ROOT_MESSAGE_ID is required}

tmux new-session -d -s "$session_name" \
  "cd '$app_dir' && \
   export BOTMUX_REPORT_SESSION_ID='$BOTMUX_REPORT_SESSION_ID' && \
   export BOTMUX_REPORT_ROOT_MESSAGE_ID='$BOTMUX_REPORT_ROOT_MESSAGE_ID' && \
   exec '$runner'"
