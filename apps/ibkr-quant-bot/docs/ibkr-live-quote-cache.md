# IBKR Live Quote Cache Runbook

This runbook covers the standalone SMART quote subscription used by the live
rotation strategy. The process maintains a bounded local cache for QQQ, SOXL,
and SOXS. It is market-data-only and must never run with trading permission.

Do not put account IDs, credentials, positions, orders, or raw account output
in this document or in quote-cache diagnostics.

## Runtime Contract

- Live checkout: `/home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot`
- tmux session: `ibkr-live-quote-cache`
- command: `python -m ibkr_quant_bot.cli stream-live-quotes`
- default cache: `.ibkr_bot_state/semiconductor_rotation_intraday/live-quotes.json`
- symbols: QQQ, SOXL, and SOXS on SMART
- refresh: atomic file replacement every one second
- memory bound: 100 samples per symbol, 300 samples total
- stale threshold used by the strategy: three seconds

The process reconnects after transient Gateway and network errors. A code
error can still terminate the tmux session, so the process and file freshness
must both be checked. tmux does not survive a machine reboot.

## Safety Environment

Always force these values for the subscription process, even if the live
checkout `.env` permits trading:

```text
IBKR_READONLY=true
IBKR_DRY_RUN=true
IBKR_ALLOW_LIVE_TRADING=false
IBKR_MARKET_DATA_TYPE=live
IBKR_ARCA_FALLBACK_ENABLED=false
```

Use an integer `IBKR_CLIENT_ID` reserved for this process. It must not collide
with the live strategy, Gateway heartbeat, history refresh, or a diagnostic
command. A client-ID conflict is a configuration error, not a reason to kill
another API client.

## Start

First confirm that no instance already exists:

```bash
tmux has-session -t ibkr-live-quote-cache 2>/dev/null
pgrep -af 'ibkr_quant_bot\.cli stream-live-quotes'
```

If both checks show no process, start one instance from the live checkout.
Replace `<unused-readonly-client-id>` with the ID reserved for this service:

```bash
tmux new-session -d \
  -s ibkr-live-quote-cache \
  -c /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot \
  'set -a; source .env; set +a; \
   export IBKR_READONLY=true IBKR_DRY_RUN=true; \
   export IBKR_ALLOW_LIVE_TRADING=false IBKR_MARKET_DATA_TYPE=live; \
   export IBKR_ARCA_FALLBACK_ENABLED=false; \
   export IBKR_CLIENT_ID=<unused-readonly-client-id>; \
   exec env PYTHONPATH=src python -m ibkr_quant_bot.cli stream-live-quotes'
```

Do not start a second instance to repair a stale file. Diagnose the existing
process first, then perform one controlled restart if necessary.

## Quick Health Check

Confirm the tmux session, Python process, recent pane output, and bounded cache
file:

```bash
tmux has-session -t ibkr-live-quote-cache 2>/dev/null \
  && echo 'quote cache process: running'
pgrep -af 'ibkr_quant_bot\.cli stream-live-quotes'
tmux capture-pane -pt ibkr-live-quote-cache -S -50
stat -c 'cache bytes=%s modified=%y' \
  /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/.ibkr_bot_state/semiconductor_rotation_intraday/live-quotes.json
```

Inspect sample counts and freshness without printing prices or account data:

```bash
cd /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot
python - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path('.ibkr_bot_state/semiconductor_rotation_intraday/live-quotes.json')
payload = json.loads(path.read_text())
now = datetime.now(timezone.utc)
generated = datetime.fromisoformat(payload['generated_at'])
print(f"source={payload['source']}")
print(f"file_age_ms={(now - generated).total_seconds() * 1000:.1f}")
for symbol, rows in payload['symbols'].items():
    observed = datetime.fromisoformat(rows[-1]['observed_at'])
    print(
        f"{symbol}: samples={len(rows)} "
        f"latest_age_ms={(now - observed).total_seconds() * 1000:.1f}"
    )
PY
```

Healthy during an active market-data session means:

- exactly one subscription process is running;
- `source=SMART`;
- all three symbols are present;
- every accepted ticker explicitly reports IBKR market-data type `1` (live);
- no symbol exceeds 100 samples;
- the file and every latest sample are normally less than three seconds old;
- the pane is not repeating reconnect or client-ID errors; and
- live strategy output normally says `live_quote_source=cache`.

Each symbol in the live polling summary also includes
`quote_market_time`, `quote_received_at`, `quote_observed_at`,
`quote_published_at`, and `quote_age_ms`. A snapshot fallback can report
`quote_market_time=null` when IBKR supplies no exchange last-trade timestamp;
do not replace it with a local clock value.

QQQ is emitted as a separate `benchmark_quote` object with `role=benchmark`,
its `latest_trade_price` (only when IBKR supplies a valid last trade), reference
price, source exchanges, and the same timing fields. It has no `action` field
because QQQ is a regime input, not an order candidate. SOXL and SOXS remain in
the strategy decision list.

Each SOXL/SOXS decision exposes the latest trade price separately from the
reference price, plus `position_status`, `strategy_status`, `order_status`, the
configured stop/take percentages, calculated protection prices for an open
position, broker-active stop/take prices, and `protection_status`. Never label
the ask, bid, or prior close as a latest trade when `quote.last` is unavailable.

If the file is stale, the strategy requests a concurrent SMART snapshot with
no fixed sleep. If that complete fallback group also fails, the strategy fails
closed and does not submit an order.

Both the streaming writer and snapshot fallback reject ticker objects whose
IBKR `marketDataType` is missing or is not `1`. Requesting live mode is not
treated as proof that the returned data is live.

## Latency Check

Each sample contains:

- `market_time`: exchange last-trade time from generic tick 233;
- `received_at`: time ib-insync received the API update;
- `observed_at`: time the cache loop processed the update; and
- `published_at`: the sample's first atomic file publication time.

The file-level `generated_at` is the most recent atomic replacement time. For
exchange latency, use only records where `market_time` changed. Bid/ask-only
updates can legitimately retain the previous last-trade timestamp.

The useful intervals are:

```text
market_to_receive = received_at - market_time
receive_to_process = observed_at - received_at
process_to_file = published_at - observed_at
market_to_file = published_at - market_time
```

Use multiple changed trade timestamps and report a distribution such as P50,
P95, and maximum. Do not infer exchange latency from a single sample, and do
not print bid, ask, last, account, position, or order fields in the report.

## Stop And Restart

Stop gracefully so the process cancels all market-data subscriptions:

```bash
tmux send-keys -t ibkr-live-quote-cache C-c
```

Confirm that the tmux session and process are gone before restarting:

```bash
tmux has-session -t ibkr-live-quote-cache 2>/dev/null \
  && echo 'still running' || echo 'stopped'
pgrep -af 'ibkr_quant_bot\.cli stream-live-quotes'
```

Then use the Start procedure. Do not use `kill -9` for routine maintenance.
If graceful stop does not complete, capture the pane and identify the blocking
condition before escalating.

## Code Upgrade Procedure

The live checkout is separate from the development checkout. A push alone does
not reload this process.

1. Run the full tests in the development checkout:

   ```bash
   cd /home/fwd/work/ai-games-wt-codex-7/apps/ibkr-quant-bot
   PYTHONPATH=src python -m pytest tests
   ```

2. Commit and push the reviewed change.
3. Briefly pause the live strategy schedule and confirm no strategy process is
   in flight.
4. Gracefully stop `ibkr-live-quote-cache`.
5. Sync only the reviewed runtime files into the live checkout.
6. Start one cache process and wait for a fresh, complete three-symbol file.
7. Run one forced read-only/dry-run strategy validation. It must report
   `live_quote_source=cache` and no order action.
8. Resume the live strategy schedule immediately.

Never edit live strategy parameters as part of quote-cache maintenance. Never
copy `.env`, account state, order journals, or credentials between checkouts.

## Reboot And Gateway Recovery

After a machine reboot, tmux sessions are gone. Restore in this order:

1. confirm IB Gateway/IBC is running and authenticated;
2. confirm port 4001 and the read-only API heartbeat;
3. start the quote-cache process once;
4. confirm a fresh complete cache file; and
5. confirm the strategy task is enabled for the trading session.

When Gateway disconnects without a machine reboot, the process normally stays
alive and retries every five seconds. If IBKR requires login or 2FA, approve it
first; repeated restarts cannot complete authentication.

## Resource And Disk Checks

The cache file is replaced instead of appended, so it must remain bounded.
The tmux pane is the normal diagnostic output; do not redirect the process to
an unbounded log file.

```bash
pane_pid=$(tmux list-panes -t ibkr-live-quote-cache -F '#{pane_pid}' | head -1)
child_pid=$(pgrep -P "$pane_pid" | head -1)
ps -o pid=,rss=,pcpu=,etime=,cmd= -p "${child_pid:-$pane_pid}"
du -h \
  /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/.ibkr_bot_state/semiconductor_rotation_intraday/live-quotes.json
```

Investigate if the file grows beyond the expected 300 samples, if RSS rises
continuously across several checks, or if CPU remains unexpectedly high. A
single RSS reading is not proof of a leak; look for sustained growth while the
sample counts remain capped.

## Failure Guide

| Observation | Likely cause | Response |
|---|---|---|
| No tmux session or Python process | Reboot, manual stop, or code error | Check Gateway, inspect prior context, then start one instance. |
| Repeating client-ID conflict | Another API client uses the reserved ID | Assign an unused ID; do not terminate the other client blindly. |
| Repeating reconnect message | Gateway/API/network unavailable | Check heartbeat, port 4001, IBC logs, and 2FA state. |
| Process runs but file is stale | No valid live ticks or writer failure | Inspect pane, verify SMART entitlement, then do one controlled restart if needed. |
| One symbol is missing/stale | Incomplete market-data group | Follow the market-data troubleshooting runbook; strategy fallback remains fail-closed. |
| Strategy always says `snapshot` | Cache path mismatch or stale cache | Compare `.env`, state directory, file age, and process working directory. |
| File exceeds 300 samples | Bound regression | Stop the cache process, keep strategy on fail-closed fallback, fix and retest before restart. |

Related runbooks:

- [Market-data troubleshooting](ibkr-market-data-troubleshooting.md)
- [IBKR API heartbeat](ibkr-api-heartbeat.md)
- [IBC Gateway startup](ibc-gateway-startup.md)
