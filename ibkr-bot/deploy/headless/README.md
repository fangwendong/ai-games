# Linux Headless IB Gateway Deployment

This is a Linux-only deployment guide for running IB Gateway, IBC, and the
Python IBKR bot on a headless server. It was verified on Debian 12 without a
physical GUI. Commands assume a Linux shell, `apt`, `bash`, standard Unix file
permissions, and `Xvfb`.

The intent is to keep IB Gateway, IBC, logs, settings, and the trading bot under
a normal user home directory, while installing only the minimal virtual display
package at the system level.

## Tested Host

- OS: Debian GNU/Linux 12
- Install user: `fwd`
- Install root: `/home/fwd/ibkr`
- Available `/home/fwd` space during install: 177 GB

## Migration Variables

The examples use the verified host's paths. For another Linux server, choose
these values first and keep them consistent:

| Variable | Verified value | Purpose |
|---|---|---|
| `INSTALL_USER` | `fwd` | Linux user that owns IB Gateway, IBC, logs, and bot files |
| `IBKR_HOME` | `/home/fwd/ibkr` | User-owned install root for Gateway, IBC, logs, and settings |
| `REPO_DIR` | `/home/fwd/work/ai-games-wt-codex-ibkr` | Git checkout containing `ibkr-bot` |
| `TWS_MAJOR_VRSN` | `1045` | IB Gateway major version used by IBC path conventions |
| `DISPLAY` | `:99` | Xvfb display used for the headless login window |

The provided scripts default to the verified values but support overrides:

```bash
export IBKR_HOME=/home/your-user/ibkr
export TWS_MAJOR_VRSN=1045
export DISPLAY=:99
```

Run the scripts as `INSTALL_USER`, not as root. Use `sudo` only for Linux system
packages such as `xvfb` or optional `x11vnc`.

Observed installed size:

| Path | Size |
|---|---:|
| `/home/fwd/ibkr` | 561 MB |
| `/home/fwd/.local/share/i4j_jres` | 262 MB |
| Total | about 823 MB |

## What Was Installed

Under `/home/fwd/ibkr`:

- `gateway/`: IB Gateway stable standalone
- `ibgateway/1045`: compatibility symlink to `gateway/` for IBC's expected layout
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

## Recommended Install Flow

From the repository checkout on the target server:

```bash
export IBKR_HOME=/home/fwd/ibkr
export TWS_MAJOR_VRSN=1045

cd /home/fwd/work/ai-games-wt-codex-ibkr/ibkr-bot

# Installs IB Gateway, IBC, config templates, executable permissions,
# and the IBC Gateway compatibility symlink under $IBKR_HOME.
./deploy/headless/install-userland.sh
```

The script installs only user-owned files. It does not install system packages and does not
store IBKR credentials.

Install the required virtual display package separately:

```bash
sudo apt-get update
sudo apt-get install -y xvfb
```

Start Paper Gateway:

```bash
"$IBKR_HOME/start-gateway-paper.sh"
```

For a long-running shell session, use `nohup`, `setsid`, `tmux`, `screen`, or a systemd user
service. The command starts `Xvfb` on `DISPLAY=:99` and then starts IBC + IB Gateway.

Expected first-launch state:

- `Xvfb :99` is running.
- A Java process running `ibcalpha.ibc.IbcGateway` is running.
- Logs show the Paper Trading login dialog opened.
- `127.0.0.1:4002` is not open until after a successful Gateway login.

Useful checks:

```bash
ps -ef | grep -E 'Xvfb|ibcalpha|IBGateway|ibgateway' | grep -v grep
tail -120 /home/fwd/ibkr/logs/start-gateway-paper.out
ss -ltnp | grep -E ':(4002|4001|7496|7497)\b' || true
```

If you need to interact with the first login window, install and run a localhost-only VNC
server or another X11 viewing method against `DISPLAY=:99`, then complete IBKR Paper login
and second-factor authentication manually.

## Migrating An Existing Installation

For a fresh Linux server, prefer rerunning `install-userland.sh` instead of
copying binaries. It redownloads the current IB Gateway stable standalone
installer, installs IBC, applies permissions, and recreates the compatibility
symlink.

If you are moving an already configured host and want to preserve local Gateway
settings, copy only the user-owned runtime state:

```bash
rsync -a /home/fwd/ibkr/config/ new-host:/home/fwd/ibkr/config/
rsync -a /home/fwd/ibkr/settings-paper/ new-host:/home/fwd/ibkr/settings-paper/
```

Treat these directories as sensitive if credentials are ever stored:

- `$IBKR_HOME/config/`
- `$IBKR_HOME/settings-paper/`
- bot `.env` files and SQLite databases

Do not commit these runtime files to Git. The repository should keep only
templates, scripts, and documentation.

Post-migration checklist:

```bash
command -v Xvfb
test -x "$IBKR_HOME/start-gateway-paper.sh"
test -x "$IBKR_HOME/ibc/scripts/ibcstart.sh"
test -e "$IBKR_HOME/ibgateway/$TWS_MAJOR_VRSN/jars"
"$IBKR_HOME/start-gateway-paper.sh"
```

After the login window appears and Paper login is completed, verify the API:

```bash
ss -ltnp | grep ':4002'
cd "$REPO_DIR/ibkr-bot"
ibkr-bot check-connection
```

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
chmod u+x /home/fwd/ibkr/ibc/*.sh /home/fwd/ibkr/ibc/scripts/*.sh

mkdir -p /home/fwd/ibkr/ibgateway
ln -sfn /home/fwd/ibkr/gateway /home/fwd/ibkr/ibgateway/1045
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
- IBC launch args equivalent to:
  `ibcstart.sh 1045 --gateway --tws-path=/home/fwd/ibkr --tws-settings-path=/home/fwd/ibkr/settings-paper --ibc-path=/home/fwd/ibkr/ibc --ibc-ini=/home/fwd/ibkr/config/ibc-paper.ini --mode=paper --on2fatimeout=exit`

First login still requires IBKR credentials and second-factor authentication.

On the verified host, the first successful launch reached the Paper Trading login dialog on
`DISPLAY=:99` with log lines like:

```text
IBC: version: 3.24.0
IBC: Login dialog WINDOW_OPENED: LoginState is LOGGED_OUT
IBC: Setting Trading mode = paper
```

Before login, `127.0.0.1:4002` is not expected to listen yet. The API port opens only after
Gateway login and API initialization complete.

The repo start script includes two compatibility fixes found during installation:

- IBC 3.24.0 does not accept the old `-inline` argument; call `ibcstart.sh` with explicit
  version, Gateway, path, mode, and 2FA timeout arguments.
- The standalone Gateway installer writes to `/home/fwd/ibkr/gateway`, but IBC looks under
  `/home/fwd/ibkr/ibgateway/1045`; create that symlink during install.

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
