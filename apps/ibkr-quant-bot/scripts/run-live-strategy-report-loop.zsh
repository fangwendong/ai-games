#!/usr/bin/env zsh
emulate -L zsh
set -uo pipefail

script_dir=${0:A:h}
app_dir=${script_dir:h}
runner="$script_dir/run-live-strategy-report.zsh"
state_dir="$app_dir/.ibkr_bot_state/live-strategy-reporter"
mkdir -p "$state_dir"
last_report_minute_file="$state_dir/last-report-minute.txt"

while true; do
  # Deterministic normal-session shutdown. Do not depend solely on a botmux
  # task being delivered to and acted on by an AI session after the close.
  et_weekday=$((10#$(TZ=America/New_York date +%u)))
  et_hhmm=$((10#$(TZ=America/New_York date +%H%M)))
  if (( et_weekday >= 6 || et_hhmm >= 1600 )); then
    log_tmp="$state_dir/latest-run.log.tmp.$$"
    print -r -- "shutdown_reason=market_closed" >"$log_tmp"
    print -r -- "strategy_interval_seconds=10" >>"$log_tmp"
    print -r -- "report_interval_seconds=60" >>"$log_tmp"
    print -r -- "runner_exit=0" >>"$log_tmp"
    mv -f "$log_tmp" "$state_dir/latest-run.log"
    exit 0
  fi

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
  current_report_minute=$(TZ=America/New_York date +%Y%m%d%H%M)
  last_report_minute=""
  if [[ -f "$last_report_minute_file" ]]; then
    last_report_minute="$(<"$last_report_minute_file")"
  fi
  if [[ "$current_report_minute" != "$last_report_minute" ]]; then
    # Send exactly one chat report per ET minute, on the first completed
    # execution observed in that minute. This keeps the minute cadence stable
    # even if the scheduler drifts away from the old :03-only slot.
    "$runner" >"$log_tmp" 2>&1
    report_due=true
    print -r -- "$current_report_minute" >"$last_report_minute_file"
  else
    # Execute the same live strategy without re-sending chat in the same minute.
    BOTMUX_REPORT_DRY_SEND=true "$runner" >"$log_tmp" 2>&1
    report_due=false
  fi
  runner_exit=$?
  print -r -- "strategy_interval_seconds=10" >>"$log_tmp"
  print -r -- "report_interval_seconds=60" >>"$log_tmp"
  print -r -- "scheduled_second=$target_second" >>"$log_tmp"
  print -r -- "report_minute=$current_report_minute" >>"$log_tmp"
  print -r -- "report_due=$report_due" >>"$log_tmp"
  print -r -- "runner_exit=$runner_exit" >>"$log_tmp"
  mv -f "$log_tmp" "$state_dir/latest-run.log"
done
