# IBC IB Gateway Startup Runbook

This runbook documents the local IBKR Gateway startup path used by this host.
It is intentionally focused on read-only account and market-data access.

Do not commit IBKR usernames, passwords, session tokens, or log excerpts that
contain secrets.

## Current Startup Command

Run IB Gateway through IBC on display `:1`:

```bash
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

For foreground diagnostics in the same terminal:

```bash
export DISPLAY=:1
/opt/ibc/gatewaystart.sh -inline
```

The non-inline form opens an `xterm` titled similar to `IBC (GATEWAY 1045)` and
then launches IB Gateway from there.

## Paths

The installed IBC launcher currently uses these paths:

| Purpose | Path |
|---|---|
| IBC startup script | `/opt/ibc/gatewaystart.sh` |
| IBC config | `/home/fwd/ibc/config.ini` |
| IBC logs | `/home/fwd/ibc/logs` |
| IB Gateway install/settings root | `/home/fwd/Jts` |
| IB Gateway major version | `1045` |
| Expected live API port | `4001` |

`/opt/ibc/gatewaystart.sh` exports the relevant environment variables and then
calls `/opt/ibc/scripts/displaybannerandlaunch.sh`, which calls the lower-level
IBC startup flow and eventually starts the Java class
`ibcalpha.ibc.IbcGateway`.

## Config Values That Matter

The important settings in `/home/fwd/ibc/config.ini` are:

```ini
TradingMode=live
OverrideTwsApiPort=4001
ReadOnlyApi=yes
ReadOnlyLogin=no
SecondFactorAuthenticationTimeout=180
ExitAfterSecondFactorAuthenticationTimeout=no
ReloginAfterSecondFactorAuthenticationTimeout=no
```

Meaning:

- `TradingMode=live` logs into the live account, not paper.
- `OverrideTwsApiPort=4001` makes the local TWS API listen on port `4001`.
- `ReadOnlyApi=yes` prevents API clients from submitting, modifying, or
  cancelling orders.
- `ReadOnlyLogin=no` means the account still follows normal login and 2FA.
  Read-only protection is applied at the API layer.

The local Python bot also connects with `IBKR_READONLY=true` by default, so the
client side and Gateway side are both read-only.

## Login Sequence

After running the startup command:

1. IBC starts IB Gateway build `1045` from `/home/fwd/Jts`.
2. IBC reads `/home/fwd/ibc/config.ini`.
3. IBC opens the IB Gateway login dialog on display `:1`.
4. IBC fills the configured username/password from `config.ini`.
5. IBC clicks `Log In`.
6. IBKR prompts for second factor authentication.
7. The user approves the IBKR Mobile 2FA prompt.
8. IB Gateway completes login.
9. IBC opens the Gateway configuration dialog.
10. IBC ensures `ReadOnlyApi=yes` and API port `4001`.
11. Gateway starts listening locally on `4001`.

## First Login vs Later Logins

On a fresh machine or fresh IB Gateway profile, the first login may require
interactive browser or graphical login steps before IBC can fully automate the
session. Complete that first login manually on display `:1`, including any IBKR
web/browser prompt, agreements, trusted-device prompts, or 2FA approval.

After the first successful login, IBKR/Gateway has enough local trusted-session
state for later IBC starts to proceed without repeating the browser login flow.
Later starts usually only require the normal IBKR Mobile 2FA approval.

If IBKR asks for browser login again, treat it as a fresh interactive login:

1. Make sure display `:1` is accessible.
2. Start Gateway with IBC.
3. Complete the browser or Gateway login prompts manually.
4. Approve IBKR Mobile 2FA.
5. Verify that IBC applies `ReadOnlyApi=yes` and port `4001`.

Common reasons IBKR may ask for browser login again include a new machine
fingerprint, cleared Gateway/browser profile state, expired trusted-device
state, password/security changes, or an IBKR-side security challenge.

Expected successful log lines:

```text
Login has completed
Setting ReadOnlyApi
Read-Only API checkbox is already set to: true
TWS API socket port is already set to 4001
Configuration tasks completed
```

## Verify Startup

Check that IBC and Gateway are running:

```bash
ps -ef | grep -E 'ibgateway|IbcGateway|ibcstart|java' | grep -v grep
```

Check that the local API port is listening:

```bash
ss -ltnp | grep -E '4001|4002|7496|7497'
```

For this live IBC setup, the expected result is a Java process listening on
`4001`:

```text
*:4001  users:(("java",pid=...,fd=...))
```

Check current IBC logs:

```bash
tail -n 200 /home/fwd/ibc/logs/ibc-3.24.1_GATEWAY-1045_Sunday.txt
```

The exact log filename changes by weekday.

## Query Through The Bot

From the project:

```bash
cd /home/fwd/work/ai-games/apps/ibkr-quant-bot
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4001
export IBKR_TRADING_MODE=live
export IBKR_READONLY=true
export IBKR_DRY_RUN=true
export IBKR_MARKET_DATA_TYPE=delayed
export PYTHONPATH=src
```

Query balance:

```bash
python3 -m ibkr_quant_bot.cli balance
```

Query positions:

```bash
python3 -m ibkr_quant_bot.cli positions
```

Query a quote:

```bash
python3 -m ibkr_quant_bot.cli quote SOXS
```

## Restart Procedure

Stop old IBC/Gateway processes:

```bash
pkill -f 'ibcalpha.ibc.IbcGateway'
pkill -f 'ibcstart.sh'
```

Confirm the API port is closed:

```bash
ss -ltnp | grep -E '4001|4002|7496|7497' || true
```

Start again:

```bash
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

Approve IBKR Mobile 2FA when prompted, then verify port `4001`.

## Troubleshooting

`process is already running`

: `gatewaystart.sh` found an existing Java process using the same IBC config.
  Stop the old process first or use the running instance.

No `4001` listener

: Gateway has not completed login or API configuration. Check the IBC log for
  login, 2FA, or configuration errors.

`INVALID_USERNAME_OR_BAD_IP` or `Authorization failed`

: IBKR rejected the login. Check credentials in `/home/fwd/ibc/config.ini`,
  remove duplicate `IbLoginId`/`IbPassword` entries, and retry.

2FA dialog appears but login never completes

: Approve the IBKR Mobile prompt within the configured timeout. The current
  timeout is `SecondFactorAuthenticationTimeout=180`.

API queries work but orders must not be possible

: Confirm both layers are read-only:

```bash
grep -n 'ReadOnlyApi' /home/fwd/ibc/config.ini
cd /home/fwd/work/ai-games/apps/ibkr-quant-bot
PYTHONPATH=src python3 -m ibkr_quant_bot.cli doctor
```

The expected Gateway setting is `ReadOnlyApi=yes`; the expected bot setting is
`"readonly": true`.
