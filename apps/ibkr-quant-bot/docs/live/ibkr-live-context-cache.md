# IBKR Live Context Cache Runbook

This runbook covers the read-only process that precomputes the current IBKR
regular-session calendar, completed SMART 5-minute bars, and conservative
tradable-capital value used by the live rotation strategy. It removes repeated
calendar, historical-bar, and balance requests from the one-minute strategy
path without changing signal or exit rules.

Do not put account IDs, credentials, positions, orders, or prices in service
health reports.

## Runtime Contract

- Live checkout: `/home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot`
- tmux session: `ibkr-live-context-cache`
- command: `python -m ibkr_quant_bot.cli cache-live-context`
- default cache: `.ibkr_bot_state/semiconductor_rotation_intraday/live-context.json`
- source: one complete SMART group for QQQ, SOXL, and SOXS
- calendar refresh: once per New York trading date
- file/capital refresh: once per minute
- bar refresh: once per completed 5-minute bucket
- consumer stale threshold: 420 seconds
- tradable-capital stale threshold: 90 seconds
- singleton guard: a non-blocking advisory lock rejects a second writer

The file is flushed, `fsync`ed, and atomically replaced and contains one current-session bar array per
symbol plus one USD amount; it contains no account identifier and does not grow
across days. The capital amount is the lower of `TotalCashValue` and
`AvailableFunds`; `BuyingPower` is never used. Before sizing an order, the
strategy subtracts `IBKR_ENTRY_CASH_RESERVE_USD` (default 10 USD) for
commission and cash headroom. The strategy accepts the cache only when
the version, date, source, bar size, complete symbol group, file age, per-bar
timestamps, and normal live freshness checks all pass.

If a calendar or bar check fails, the strategy immediately uses the original
IBKR request. It does not sleep waiting for the cache. If both cache
and direct IBKR data fail validation, the strategy fails closed and submits no
new order. If only tradable capital is missing, stale, or invalid, the strategy
reports the fallback and uses configured `IBKR_MAX_ORDER_NOTIONAL` (4000 USD in
live) minus the same reserve, producing a 3990 USD fallback entry ceiling.
Mandatory pre-close flatten still runs before bar loading.

After a two-second publication grace at each five-minute boundary, every
symbol must contain the theoretically latest completed bar. If the cached group
is even one bar behind, the strategy immediately fetches the full SMART group
from IBKR. The direct response must pass the same exact completed-bar check;
otherwise the strategy fails closed rather than evaluating an older signal.

## Safety Environment

Always force these values for this process:

```text
IBKR_READONLY=true
IBKR_DRY_RUN=true
IBKR_ALLOW_LIVE_TRADING=false
IBKR_MARKET_DATA_TYPE=live
IBKR_ARCA_FALLBACK_ENABLED=false
```

Reserve an IBKR client ID that is not used by the live strategy, quote cache,
heartbeat, history refresh, or diagnostics.

## Start

Confirm that no copy is already running, then start one instance:

```bash
tmux has-session -t ibkr-live-context-cache 2>/dev/null
pgrep -af 'ibkr_quant_bot\.cli cache-live-context'

tmux new-session -d \
  -s ibkr-live-context-cache \
  -c /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot \
  'set -a; source .env; set +a; \
   export IBKR_READONLY=true IBKR_DRY_RUN=true; \
   export IBKR_ALLOW_LIVE_TRADING=false IBKR_MARKET_DATA_TYPE=live; \
   export IBKR_ARCA_FALLBACK_ENABLED=false; \
   export IBKR_CLIENT_ID=<unused-readonly-client-id>; \
   exec env PYTHONPATH=src python -m ibkr_quant_bot.cli cache-live-context'
```

The first publication outside regular hours contains the precomputed session
calendar and no bars. During regular hours the first successful refresh adds
the complete three-symbol bar group.

## Health Check

Resource monitoring may check only process and file activity; it must not parse
or report symbols, bars, prices, SMART/ARCA content, or account data:

```bash
tmux has-session -t ibkr-live-context-cache 2>/dev/null
pgrep -af 'ibkr_quant_bot\.cli cache-live-context'
stat -c 'cache bytes=%s modified=%y' \
  /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/.ibkr_bot_state/semiconductor_rotation_intraday/live-context.json
```

The file should normally change once per minute, while its bar arrays change
only after a completed five-minute bucket. The strategy reports
`market_session_source=cache` and
`live_bar_source=cache` on a cache hit. A `broker` source with `cache_reason`
means the safe direct fallback was used.

## Stop And Restart

```bash
tmux send-keys -t ibkr-live-context-cache C-c
tmux has-session -t ibkr-live-context-cache 2>/dev/null \
  && echo 'still running' || echo 'stopped'
```

Do not start a second copy to repair a stale file. The second writer is rejected
by the advisory lock. Inspect the existing tmux
pane and IB heartbeat first, then perform one controlled restart if needed.
After a machine reboot, restore Gateway first, then the quote cache and context
cache, and only then enable the live polling task.

## Validation After Upgrade

1. Run the full test suite in the development checkout.
2. Run one read-only/dry-run strategy execution with a fresh cache.
3. Confirm cache-source output and zero order actions.
4. Stop the context cache and run the same safe command again.
5. Confirm immediate broker fallback, no wait loop, and zero order actions.
6. Start exactly one context-cache process again.

Backtests continue to read their isolated historical cache and do not consume
this live runtime file.
