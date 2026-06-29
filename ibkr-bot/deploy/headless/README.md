# Headless IB Gateway Deployment

This notes the deployment pattern tested on a Debian 12 server without a physical GUI. The intent is to keep IB Gateway, IBC, logs, settings, and the trading bot under a normal user home directory, while installing only the minimal virtual display package at the system level.

## Tested Host

- OS: Debian GNU/Linux 12
- Install user: `fwd`
- Install root: `/home/fwd/ibkr`
- Available `/home/fwd` space during install: 177 GB

Observed installed size:

| Path | Size |
|---|---:|
| `/home/fwd/ibkr` | 561 MB |
| `/home/fwd/.local/share/i4j_jres` | 262 MB |
| Total | about 823 MB |

## What Was Installed

Under `/home/fwd/ibkr`:

- `gateway/`: IB Gateway stable standalone
- `ibc/`: IBC 3.24.0
- `config/ibc-paper.ini`: Paper Trading IBC config template
- `start-gateway-paper.sh`: start script for Xvfb + IBC + IB Gateway
- `downloads/`: downloaded installers, not needed in Git
- `logs/`: runtime logs
- `settings-paper/`: Gateway settings, created on first launch

The IB Gateway installer placed its bundled JRE under `/home/fwd/.local/share/i4j_jres`, so no system Java package was required.

## System Dependency

`Xvfb` was missing on the tested server and requires root/sudo. This is the only required system package for the minimal headless path:

```bash
sudo apt-get update
sudo apt-get install -y xvfb
```

Optional, only if a remote visual login/config view is needed:

```bash
sudo apt-get install -y x11vnc
```

Bind VNC to localhost and access it through an SSH tunnel. Do not expose VNC or IBKR API ports to the public internet.

## Install IB Gateway

```bash
mkdir -p /home/fwd/ibkr/{downloads,logs,run,config}
cd /home/fwd/ibkr/downloads

wget -O ibgateway-stable-standalone-linux-x64.sh \
  https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh

chmod u+x ibgateway-stable-standalone-linux-x64.sh
./ibgateway-stable-standalone-linux-x64.sh -q -dir /home/fwd/ibkr/gateway -overwrite
```

The tested installer was about 321 MB and installed Gateway to about 240 MB.

## Install IBC

```bash
cd /home/fwd/ibkr/downloads
wget -O IBCLinux-3.24.0.zip \
  https://github.com/IbcAlpha/IBC/releases/download/3.24.0/IBCLinux-3.24.0.zip

rm -rf /home/fwd/ibkr/ibc
mkdir -p /home/fwd/ibkr/ibc
unzip -q IBCLinux-3.24.0.zip -d /home/fwd/ibkr/ibc
```

IBC itself is small, about 424 KB in the tested install.

## Configure

Copy the templates:

```bash
cp ibc-paper.ini /home/fwd/ibkr/config/ibc-paper.ini
cp start-gateway-paper.sh /home/fwd/ibkr/start-gateway-paper.sh
chmod 600 /home/fwd/ibkr/config/ibc-paper.ini
chmod 700 /home/fwd/ibkr/start-gateway-paper.sh
```

The template intentionally leaves `IbLoginId` and `IbPassword` blank. With blank credentials, Gateway displays the login dialog on the virtual display. If credentials are later added for Paper Trading automation, keep the config file owned by `fwd` with mode `600`, and treat it as a secret.

## Start

After `xvfb` is installed:

```bash
/home/fwd/ibkr/start-gateway-paper.sh
```

The script uses:

- `DISPLAY=:99`
- `TWS_MAJOR_VRSN=1045`
- `TRADING_MODE=paper`
- `OverrideTwsApiPort=4002`
- settings dir `/home/fwd/ibkr/settings-paper`

First login still requires IBKR credentials and second-factor authentication.

## Bot Connection

The bot should connect locally:

```env
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=17
IBKR_TRADING_MODE=paper
IBKR_DRY_RUN=true
IBKR_ALLOW_LIVE=false
```

Then:

```bash
cd /home/fwd/work/ai-games-wt-codex-ibkr/ibkr-bot
source .venv/bin/activate
ibkr-bot check-connection
```

## Security Notes

- Do not expose `4001`, `4002`, `7496`, or `7497` to the public internet.
- Run the bot and IB Gateway on the same host and connect via `127.0.0.1`.
- Keep Paper Trading as the default until connection, orders, fills, and alerts are verified.
- The project defaults remain `IBKR_DRY_RUN=true` and `IBKR_ALLOW_LIVE=false`.
- IBC is useful for automation, but saving IBKR credentials on a server is a material security decision.

## Why Not User-Local Xvfb

It is technically possible to download Debian packages and unpack `xvfb` plus shared-library dependencies into a user directory. That path is brittle and harder to maintain. The cleaner boundary is:

- system package: `xvfb`
- user directory: IB Gateway, IBC, settings, logs, bot code

