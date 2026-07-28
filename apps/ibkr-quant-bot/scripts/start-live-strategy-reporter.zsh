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
state_dir="$app_dir/.ibkr_bot_state/live-strategy-reporter"
mkdir -p "$state_dir"

if tmux has-session -t "$session_name" 2>/dev/null; then
  exit 0
fi

root_message_id="${BOTMUX_REPORT_ROOT_MESSAGE_ID:-}"
if [[ -z "$root_message_id" && -f "$state_dir/root-message-id.txt" ]]; then
  root_message_id="$(<"$state_dir/root-message-id.txt")"
fi
report_session_id="${BOTMUX_REPORT_SESSION_ID:-${BOTMUX_SESSION_ID:-}}"

: ${root_message_id:?BOTMUX_REPORT_ROOT_MESSAGE_ID is required}
: ${report_session_id:?BOTMUX_REPORT_SESSION_ID is required}
print -r -- "$root_message_id" >"$state_dir/root-message-id.txt"

tmux new-session -d -s "$session_name" \
  -e "BOTMUX_SESSION_ID=$report_session_id" \
  -e "BOTMUX_REPORT_SESSION_ID=$report_session_id" \
  -e "BOTMUX_REPORT_ROOT_MESSAGE_ID=$root_message_id" \
  "cd '$app_dir' && \
   exec '$runner'"
