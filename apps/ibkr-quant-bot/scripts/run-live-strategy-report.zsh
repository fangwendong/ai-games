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

export IBKR_MARKET_DATA_TYPE=live
export IBKR_ARCA_FALLBACK_ENABLED=false

if [[ ${BOTMUX_REPORT_SAFE_TEST:-false} == true ]]; then
  export IBKR_READONLY=true
  export IBKR_DRY_RUN=true
  export IBKR_ALLOW_LIVE_TRADING=false
fi

market_gate=$(python - <<'PY'
from datetime import datetime, time
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("America/New_York"))
print("open" if now.weekday() < 5 and time(9, 30) <= now.time() < time(16, 0) else "closed")
PY
)
if [[ $market_gate != open && ${BOTMUX_REPORT_FORCE_RUN:-false} != true ]]; then
  exit 0
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT INT TERM
raw_output="$tmp_dir/strategy-output.log"
summary_output="$tmp_dir/strategy-summary.txt"
started_at_ms=$(date +%s%3N)

set +e
PYTHONPATH=src timeout 70s python -m ibkr_quant_bot.cli intraday-momentum \
  --profile rotation-hysteresis-v3-soxl-gate25 >"$raw_output" 2>&1
strategy_exit_code=$?
set -e
ended_at_ms=$(date +%s%3N)

if grep -q "market closed: skipping intraday_momentum scan" "$raw_output"; then
  exit 0
fi

PYTHONPATH=src python -m ibkr_quant_bot.live_report \
  --input "$raw_output" \
  --exit-code "$strategy_exit_code" \
  --started-at-ms "$started_at_ms" \
  --ended-at-ms "$ended_at_ms" >"$summary_output"

state_dir=.ibkr_bot_state/live-strategy-reporter
mkdir -p "$state_dir"
summary_tmp="$state_dir/latest-summary.txt.tmp.$$"
cp "$summary_output" "$summary_tmp"
mv -f "$summary_tmp" "$state_dir/latest-summary.txt"

if [[ ${BOTMUX_REPORT_DRY_SEND:-false} == true ]]; then
  print -r -- "$(<"$summary_output")"
else
: ${BOTMUX_REPORT_ROOT_MESSAGE_ID:?BOTMUX_REPORT_ROOT_MESSAGE_ID is required}
  botmux send --quote "$BOTMUX_REPORT_ROOT_MESSAGE_ID" --no-mention \
    --content-file "$summary_output"
fi

exit "$strategy_exit_code"
