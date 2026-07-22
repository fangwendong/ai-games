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

append_status=0
PYTHONPATH=src python -m ibkr_quant_bot.cli append-live-review-log || append_status=$?

"$script_dir/stop-live-strategy-reporter.zsh"
stop_status=$?

if (( append_status != 0 )); then
  exit "$append_status"
fi

exit "$stop_status"
