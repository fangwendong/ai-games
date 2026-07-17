#!/usr/bin/env zsh
emulate -L zsh
set -uo pipefail

script_dir=${0:A:h}
app_dir=${script_dir:h}
runner="$script_dir/run-live-strategy-report.zsh"
state_dir="$app_dir/.ibkr_bot_state/live-strategy-reporter"
mkdir -p "$state_dir"

while true; do
  # Use fixed wall-clock slots instead of sleeping after a run. A slow run may
  # skip a slot, but executions never overlap or drift into a tight retry loop.
  now_epoch=$(date +%s)
  remainder=$(( (now_epoch - 3) % 10 ))
  if (( remainder < 0 )); then
    remainder=$((remainder + 10))
  fi
  sleep_seconds=$((10 - remainder))
  target_epoch=$((now_epoch + sleep_seconds))
  target_second=$((target_epoch % 60))
  sleep "$sleep_seconds"

  log_tmp="$state_dir/latest-run.log.tmp.$$"
  if (( target_second == 3 )); then
    # The :03 execution is also the once-per-minute chat report. Respect an
    # inherited BOTMUX_REPORT_DRY_SEND for explicit safe validation.
    "$runner" >"$log_tmp" 2>&1
    report_due=true
  else
    # Execute the same live strategy every ten seconds without sending chat.
    BOTMUX_REPORT_DRY_SEND=true "$runner" >"$log_tmp" 2>&1
    report_due=false
  fi
  runner_exit=$?
  print -r -- "strategy_interval_seconds=10" >>"$log_tmp"
  print -r -- "report_interval_seconds=60" >>"$log_tmp"
  print -r -- "scheduled_second=$target_second" >>"$log_tmp"
  print -r -- "report_due=$report_due" >>"$log_tmp"
  print -r -- "runner_exit=$runner_exit" >>"$log_tmp"
  mv -f "$log_tmp" "$state_dir/latest-run.log"
done
