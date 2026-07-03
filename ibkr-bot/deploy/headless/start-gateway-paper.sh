#!/usr/bin/env bash
set -euo pipefail

export IBKR_HOME="${IBKR_HOME:-/home/fwd/ibkr}"
export DISPLAY="${DISPLAY:-:99}"

IBC_PATH="$IBKR_HOME/ibc"
IBC_INI="$IBKR_HOME/config/ibc-paper.ini"
TWS_PATH="$IBKR_HOME"
TWS_SETTINGS_PATH="$IBKR_HOME/settings-paper"
LOG_PATH="$IBKR_HOME/logs"
TWS_MAJOR_VRSN="${TWS_MAJOR_VRSN:-1045}"

mkdir -p "$TWS_SETTINGS_PATH" "$LOG_PATH" "$IBKR_HOME/run"
mkdir -p "$IBKR_HOME/ibgateway"
ln -sfn "$IBKR_HOME/gateway" "$IBKR_HOME/ibgateway/$TWS_MAJOR_VRSN"

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfb is not installed. Install it with: sudo apt-get install -y xvfb" >&2
  exit 20
fi

XVFB_PID_FILE="$IBKR_HOME/run/xvfb.pid"
if [[ ! -s "$XVFB_PID_FILE" ]] || ! kill -0 "$(cat "$XVFB_PID_FILE")" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1280x900x24 -nolisten tcp >"$LOG_PATH/xvfb.log" 2>&1 &
  echo $! >"$XVFB_PID_FILE"
  sleep 2
fi

export TWS_MAJOR_VRSN
export IBC_INI
export TRADING_MODE=paper
export TWOFA_TIMEOUT_ACTION=exit
export IBC_PATH
export TWS_PATH
export TWS_SETTINGS_PATH
export LOG_PATH
export TWSUSERID=
export TWSPASSWORD=
export FIXUSERID=
export FIXPASSWORD=
export JAVA_PATH=
export APP=GATEWAY

exec "$IBC_PATH/scripts/ibcstart.sh" "$TWS_MAJOR_VRSN" \
  --gateway \
  --tws-path="$TWS_PATH" \
  --tws-settings-path="$TWS_SETTINGS_PATH" \
  --ibc-path="$IBC_PATH" \
  --ibc-ini="$IBC_INI" \
  --mode="$TRADING_MODE" \
  --on2fatimeout="$TWOFA_TIMEOUT_ACTION"
