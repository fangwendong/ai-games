#!/usr/bin/env bash
set -euo pipefail

IBKR_HOME="${IBKR_HOME:-/home/fwd/ibkr}"
IBC_VERSION="${IBC_VERSION:-3.24.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$IBKR_HOME"/{downloads,logs,run,config}

cd "$IBKR_HOME/downloads"

if [[ ! -f ibgateway-stable-standalone-linux-x64.sh ]]; then
  wget -O ibgateway-stable-standalone-linux-x64.sh \
    https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
fi

chmod u+x ibgateway-stable-standalone-linux-x64.sh
./ibgateway-stable-standalone-linux-x64.sh -q -dir "$IBKR_HOME/gateway" -overwrite

if [[ ! -f "IBCLinux-${IBC_VERSION}.zip" ]]; then
  wget -O "IBCLinux-${IBC_VERSION}.zip" \
    "https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IBCLinux-${IBC_VERSION}.zip"
fi

rm -rf "$IBKR_HOME/ibc"
mkdir -p "$IBKR_HOME/ibc"
unzip -q "IBCLinux-${IBC_VERSION}.zip" -d "$IBKR_HOME/ibc"
chmod u+x "$IBKR_HOME"/ibc/*.sh "$IBKR_HOME"/ibc/scripts/*.sh

# IBC expects Gateway at <tws-path>/ibgateway/<major-version>, while the
# standalone Gateway installer writes directly to $IBKR_HOME/gateway.
mkdir -p "$IBKR_HOME/ibgateway"
ln -sfn "$IBKR_HOME/gateway" "$IBKR_HOME/ibgateway/${TWS_MAJOR_VRSN:-1045}"

cp "$SCRIPT_DIR/ibc-paper.ini" "$IBKR_HOME/config/ibc-paper.ini"
cp "$SCRIPT_DIR/start-gateway-paper.sh" "$IBKR_HOME/start-gateway-paper.sh"
chmod 600 "$IBKR_HOME/config/ibc-paper.ini"
chmod 700 "$IBKR_HOME/start-gateway-paper.sh"

echo "Installed userland IBKR files under $IBKR_HOME"
echo "Install Xvfb separately with: sudo apt-get install -y xvfb"
