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

  # Run at second 3 of each minute. This gives the completed five-minute bar
  # producer its two-second publication grace before the consumer validates
  # the theoretically latest bar.
  now_second=$((10#$(date +%S)))
  if (( now_second < 3 )); then
    sleep_seconds=$((3 - now_second))
  else
    sleep_seconds=$((63 - now_second))
  fi
  sleep "$sleep_seconds"
done
