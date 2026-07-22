# IBKR API Heartbeat Runbook

This runbook documents the local IB Gateway watchdog and API heartbeat. Its
purpose is to distinguish a running Java process from a usable, authenticated
IBKR API session without placing orders or changing account state.

Do not commit IBKR credentials, account IDs, session tokens, or unredacted
Gateway logs.

## What Runs

The user crontab invokes the installed watchdog once per minute:

```cron
* * * * * /home/fwd/.local/bin/ibkr-gateway-watchdog
```

The canonical script is tracked at `scripts/ibkr-gateway-watchdog`. The
installed copy is `/home/fwd/.local/bin/ibkr-gateway-watchdog`.

Each invocation performs these checks in order:

1. Acquire `/tmp/ibkr-gateway-watchdog-v2.lock` so overlapping cron runs do
   not start multiple Gateway processes.
2. Check for the IBC Gateway Java process or an IBC startup process.
3. Start Gateway through IBC only when neither process exists.
4. Check TCP port `4001` when Gateway exists.
5. At most once every five minutes, connect with read-only client ID `97` and
   request IBKR server time through `ibkr-bot heartbeat`.
6. On success, write the current Unix timestamp to
   `/tmp/ibkr-gateway-heartbeat.stamp`.

The cron frequency and API frequency are intentionally different. The
one-minute process/port check detects local failures promptly, while the
five-minute throttle avoids unnecessary authenticated API connection churn.

## What Counts As Healthy

All of the following should be true:

- the cron entry exists;
- the Gateway Java process is running;
- port `4001` is listening;
- the heartbeat stamp is less than about six minutes old; and
- a manual server-time request succeeds when deeper verification is needed.

The stamp is the normal success record. Successful heartbeat calls are not
appended to the watchdog log, so an old log modification time by itself does
not mean the task stopped. The log is reserved for starts and failures.

The stamp lives under `/tmp`, so it is expected to disappear after a reboot.
The next successful heartbeat recreates it.

## Log Retention

The watchdog applies a bounded retention policy on every cron invocation:

- `/home/fwd/ibc/logs/ibkr-gateway-watchdog.log` is truncated after it reaches
  1 MiB, with one previous copy kept as `ibkr-gateway-watchdog.log.1`;
- IBC Gateway diagnostic files matching `ibc-*_GATEWAY-*.txt` are retained for
  14 days; and
- temporary files matching `gateway-restart-*.log` are retained for 14 days.

Rotation uses copy-and-truncate because the launched IBC/Gateway process may
still hold the original log file descriptor. These rules apply only to local
startup and connectivity diagnostics. They do not remove order, fill,
position, account, or broker audit data.

Check current usage and retained files with:

```bash
du -sh /home/fwd/ibc/logs
find /home/fwd/ibc/logs -maxdepth 1 -type f \
  -printf '%s %TY-%Tm-%Td %TH:%TM %f\n' | sort -nr
```

## Quick Health Check

Verify the schedule and local Gateway state:

```bash
crontab -l | grep -F '/home/fwd/.local/bin/ibkr-gateway-watchdog'
pgrep -af 'ibcalpha\.ibc\.IbcGateway'
ss -ltnp | grep ':4001'
```

Inspect the most recent successful API heartbeat:

```bash
stat -c 'heartbeat stamp: %y' /tmp/ibkr-gateway-heartbeat.stamp
stamp=$(cat /tmp/ibkr-gateway-heartbeat.stamp)
date -d "@$stamp" '+last API heartbeat: %Y-%m-%d %H:%M:%S %Z'
date '+current time:       %Y-%m-%d %H:%M:%S %Z'
```

Inspect startup and failure messages:

```bash
tail -n 100 /home/fwd/ibc/logs/ibkr-gateway-watchdog.log
```

Run an independent read-only API round trip with a client ID that does not
collide with the scheduled heartbeat:

```bash
cd /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot
set -a
source .env
set +a
IBKR_READONLY=true \
IBKR_DRY_RUN=true \
IBKR_CLIENT_ID=98 \
PYTHONPATH=src \
  timeout 45 python -m ibkr_quant_bot.cli heartbeat
```

A successful command prints an ISO-formatted IBKR server time. This proves an
authenticated TWS API request completed; an open port alone does not.

## Failure Interpretation

| Observation | Meaning | Response |
|---|---|---|
| No Gateway or IBC startup process | Gateway exited | The next cron run starts it through IBC. |
| Gateway process exists, port `4001` closed | Login, 2FA, or API configuration is incomplete | Check IBC logs and approve 2FA. The watchdog deliberately does not restart in a loop. |
| Port `4001` open, heartbeat stamp stale | The authenticated API round trip is failing or cron is not running | Check crontab and the watchdog log, then run the manual heartbeat. |
| Manual heartbeat reports a client-ID conflict | Another API client is using that ID | Retry with an unused diagnostic ID such as `98`; leave scheduled ID `97` unchanged. |
| Heartbeat succeeds but live quotes fail | Connectivity is healthy, but market-data entitlement/session state is not | Follow `ibkr-market-data-troubleshooting.md`; do not treat heartbeat as a quote test. |

The watchdog does not automatically kill or restart a Gateway process that is
waiting for login or 2FA. Restart loops cannot satisfy IBKR authentication and
may trigger a failed-login cooldown. Human approval is still required when
IBKR requests it.

## Safety Boundary

The scheduled heartbeat forces all of these settings:

```text
IBKR_READONLY=true
IBKR_DRY_RUN=true
IBKR_CLIENT_ID=97
```

Its only broker operation is the server-time request. It does not request
quotes, inspect positions, submit orders, cancel orders, or change Gateway
configuration. Heartbeat health therefore means the API session is reachable;
it does not prove that market data is live or that the trading strategy
process is running.

## Installation And Change Checklist

After changing the tracked script:

```bash
install -m 0755 scripts/ibkr-gateway-watchdog \
  /home/fwd/.local/bin/ibkr-gateway-watchdog
bash -n scripts/ibkr-gateway-watchdog
/home/fwd/.local/bin/ibkr-gateway-watchdog
```

Then verify the heartbeat stamp advances within five minutes, or remove only
the stamp and run the watchdog once to force an immediate read-only check:

```bash
rm -f /tmp/ibkr-gateway-heartbeat.stamp
/home/fwd/.local/bin/ibkr-gateway-watchdog
stat -c '%y' /tmp/ibkr-gateway-heartbeat.stamp
```

Removing the stamp does not stop or restart Gateway. Do not remove the lock
file or kill Gateway merely to test the heartbeat.
