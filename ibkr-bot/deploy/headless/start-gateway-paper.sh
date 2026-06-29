#!/usr/bin/env bash
set -euo pipefail

export IBKR_HOME="${IBKR_HOME:-/home/fwd/ibkr}"
export DISPLAY="${DISPLAY:-:99}"

IBC_PATH="$IBKR_HOME/ibc"
IBC_INI="$IBKR_HOME/config/ibc-paper.ini"
TWS_PATH="$IBKR_HOME/gateway"
TWS_SETTINGS_PATH="$IBKR_HOME/settings-paper"
LOG_PATH="$IBKR_HOME/logs"

mkdir -p "$TWS_SETTINGS_PATH" "$LOG_PATH" "$IBKR_HOME/run"

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfb is not installed. Install it with: sudo apt-get install -y xvfb" >&2
  exit 20
fi

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1280x900x24 -nolisten tcp >"$LOG_PATH/xvfb.log" 2>&1 &
  echo $! >"$IBKR_HOME/run/xvfb.pid"
  sleep 2
fi

export TWS_MAJOR_VRSN="${TWS_MAJOR_VRSN:-1045}"
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

exec "$IBC_PATH/scripts/ibcstart.sh" -inline

