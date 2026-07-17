#!/usr/bin/env zsh
emulate -L zsh
set -uo pipefail

script_dir=${0:A:h}
app_dir=${script_dir:h}
runner="$script_dir/run-live-strategy-report.zsh"
state_dir="$app_dir/.ibkr_bot_state/live-strategy-reporter"
mkdir -p "$state_dir"

while true; do
  log_tmp="$state_dir/latest-run.log.tmp.$$"
  "$runner" >"$log_tmp" 2>&1
  runner_exit=$?
  print -r -- "runner_exit=$runner_exit" >>"$log_tmp"
  mv -f "$log_tmp" "$state_dir/latest-run.log"

  now_epoch=$(date +%s)
  sleep_seconds=$((60 - (now_epoch % 60)))
  sleep "$sleep_seconds"
done
