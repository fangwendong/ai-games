# IBKR Quant Bot

Python scaffold for connecting to Interactive Brokers market data and trading APIs through TWS or IB Gateway.

This project is intentionally guarded:

- `IBKR_READONLY=true` is the default, so broker connections are read-only unless explicitly changed.
- IB Gateway port `4001` is the default in this environment.
- `IBKR_DRY_RUN=true` is the default, so validated orders are not sent.
- Live mode requires both `IBKR_TRADING_MODE=live` and `IBKR_ALLOW_LIVE_TRADING=true`.
- Every order is checked against `IBKR_ALLOWED_SYMBOLS` and `IBKR_MAX_ORDER_NOTIONAL`.
- A submitted order must also match the account environment reported by Gateway:
  `DU...` paper accounts are rejected in live mode and `U...` production
  accounts are rejected in paper mode. Set `IBKR_ACCOUNT` when more than one
  account is exposed.
- `SELL` is reduce-only in this application: it must be covered by the current
  long position after subtracting active sell orders.

## API Choice

The implementation uses the TWS API path through TWS or IB Gateway. IBKR's current Campus documentation describes TWS API support for Python and states that customers must run Trader Workstation or IB Gateway for this API connection. The older `interactivebrokers.github.io/tws-api` site now points readers to IBKR Campus for current documentation.

- IBKR Campus TWS API docs: <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/>
- Deprecated legacy TWS API docs: <https://interactivebrokers.github.io/tws-api/>

For Python ergonomics this scaffold uses `ib-insync` as a thin client library around the TWS API. The broker boundary is isolated in `src/ibkr_quant_bot/broker.py`, so it can be replaced with the official `ibapi` package later if needed.

## Setup

1. Install and log in to TWS or IB Gateway.
2. Enable API access in TWS or Gateway settings.
3. Use a paper trading account first.
4. Install this package:

```bash
cd apps/ibkr-quant-bot
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

The CLI reads environment variables directly. If you use `.env`, load it before running commands:

```bash
set -a
source .env
set +a
```

### Runtime Isolation

Use separate checkouts for backtest/dev and live execution:

- `apps/ibkr-quant-bot/` is the development and backtest checkout.
- `/home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/` is the live checkout used by the running strategy.

Each checkout keeps its own `.env`, so editing backtest code or parameters in the dev tree does not affect the live bot unless you explicitly sync the live tree.

## Commands

Check configuration and dependency status:

```bash
ibkr-bot doctor
```

### Read-Only Live Gateway Queries

For a logged-in live IB Gateway, the common API port is `4001`. Keep `IBKR_READONLY=true` for balance, position, and quote checks:

The local IBC startup and login process is documented in [docs/ibc-gateway-startup.md](docs/ibc-gateway-startup.md).
The canonical route to every bot runbook and research note is the
[documentation index](docs/README.md). Server resource, botmux, Gateway
heartbeat, cache-process, alert-threshold, and report-format maintenance is in
[the health-monitor runbook](docs/server-health-monitor.md).
The scheduled process, port, and authenticated API health checks are documented
in [docs/ibkr-api-heartbeat.md](docs/ibkr-api-heartbeat.md).
The standalone bounded SMART subscription process, atomic quote cache, health
checks, restart procedure, latency fields, and reboot recovery are documented
in [docs/ibkr-live-quote-cache.md](docs/ibkr-live-quote-cache.md).
The separate read-only current-session calendar and completed 5-minute bar
cache, including its direct-query fallback and maintenance procedure, is
documented in
[docs/ibkr-live-context-cache.md](docs/ibkr-live-context-cache.md).
If quotes unexpectedly fall back to delayed data or the live strategy reports
that live quotes are unavailable, use
[docs/ibkr-market-data-troubleshooting.md](docs/ibkr-market-data-troubleshooting.md).
That runbook also documents how to enable real-time market data in IBKR Client
Portal and the required Market Data API acknowledgement.

All worktrees should reuse the data-disk historical cache documented in
[docs/historical-market-data.md](docs/historical-market-data.md). It includes
the canonical path plus download, read, completeness-audit, and daily refresh
commands.

The isolated long gap-down/VWAP recovery experiment and its same-period
comparison with live v2 are documented in
[docs/gap-reversion-research.md](docs/gap-reversion-research.md).
The research-only **GapGuard Fusion v1** causal state machine is documented in
[docs/hybrid-state-research.md](docs/hybrid-state-research.md).

Sanitized live fills, no-trade sessions, exit paths, and replay reconciliation
are maintained in the append-only
[live strategy review log](docs/live-strategy-review-log.md). Do not commit raw
IBKR runtime journals; they contain private broker metadata.

```bash
cd apps/ibkr-quant-bot
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4001
export IBKR_TRADING_MODE=live
export IBKR_READONLY=true
export IBKR_DRY_RUN=true
```

Fetch a quote snapshot:

```bash
ibkr-bot quote AAPL
```

If real-time market data is not subscribed, use delayed data:

```bash
export IBKR_MARKET_DATA_TYPE=delayed
ibkr-bot quote AAPL
```

Show the main balance fields: net liquidation value, cash, buying power, available funds, margin requirements, gross position value, and PnL:

```bash
ibkr-bot balance
```

Show the full raw account summary from IBKR:

```bash
ibkr-bot account
```

Show open positions:

```bash
ibkr-bot positions
```

Validate an order without sending it:

```bash
IBKR_DRY_RUN=true ibkr-bot order AAPL BUY 1 --reference-price 200
```

Run the sample moving-average strategy once:

```bash
ibkr-bot run-once AAPL --fast 5 --slow 20 --quantity 1
```

### VWAP Pullback Scanner

Scan the intraday VWAP pullback setup for `SOXL`, `TQQQ`, and `TECL`:

```bash
ibkr-bot vwap-pullback
```

The command only runs during regular US market hours, and it uses a single
order cap of `IBKR_MAX_ORDER_NOTIONAL` (default `1000`).

Automatic order submission still respects the existing safety switches:

- `IBKR_READONLY=true` suppresses order placement.
- `IBKR_DRY_RUN=true` prints the order instead of submitting it.
- `IBKR_ALLOW_LIVE_TRADING=true` is required for live trading in `live` mode.
- `IBKR_ALLOWED_SYMBOLS` still applies to the generic order command, while the
  VWAP scanner uses `IBKR_VWAP_SYMBOLS` (`SOXL,TQQQ,TECL` by default).

### Intraday Momentum Rotation

The VWAP pullback model was kept for reference, but the higher-conviction
intraday setup in this branch is the momentum rotation rule:

- 5-minute bars
- fast EMA 13
- slow EMA 21
- medium-term EMA regime filter
- lighter benchmark confirmation on `QQQ`
- enter only when price is above the fast/slow EMAs, the regime EMA, and VWAP
- require a minimum momentum score plus recent VWAP confirmation before entry
- exit on stop loss, take profit, or bearish reversal
- one open position at a time across `SOXL`, `TQQQ`, and `TECL`

Run the scanner and exit manager with the current default
`rotation-hysteresis-v2` profile:

```bash
ibkr-bot intraday-momentum
```

In live trading mode, the intraday scanners refuse delayed market data:

- The scanner reads the current regular/liquid session from IBKR contract
  details before trading. Exchange holidays are skipped explicitly, and early
  closes move the mandatory flatten window to ten minutes before the actual
  close. A missing or malformed IBKR calendar entry fails closed.
- Quote requests are forced through live market data instead of the generic
  `auto` fallback path.
- Historical bars must be fresh. By default the latest bar may be at most
  `IBKR_LIVE_BAR_MAX_AGE_SECONDS=420` seconds old, which allows normal
  completed 5-minute bars but rejects 15-20 minute delayed data.
- Entry, technical-exit, benchmark-regime, and protective-price calculations
  use completed 5-minute bars only. A bar whose five-minute interval has not
  ended is excluded so live decisions match the backtest close-bar convention.
- Live execution first reads an atomically published, complete SMART cache for
  the current session calendar and completed QQQ/SOXL/SOXS 5-minute bars. The
  read-only producer refreshes bars only when a new five-minute bucket is
  available and resolves the calendar once per New York date. A missing,
  stale, partial, wrong-date, or wrong-source cache falls through immediately
  to the original IBKR requests; it never weakens freshness guards.
- Strategy bars are restricted to the current New York regular session, so the
  opening signal cannot inherit the prior day's EMA or VWAP history.
- A large mismatch between the prior close and current-session prices blocks
  new entries as a possible split, reverse split, or unadjusted-data event.
  Fractional strategy positions also stop automation for manual corporate-
  action review. This is especially relevant to leveraged ETFs such as
  `SOXS`; normal exits remain available before the new-entry guard is applied.
- The scanner stops entering and liquidates positions during the final
  `IBKR_FLATTEN_BEFORE_CLOSE_MINUTES=10` minutes. Run the command on a schedule
  that includes this window; no software can flatten a position if it is not running.
- The mandatory flatten path runs before signal-bar and quote loading. A stale
  or incomplete three-symbol signal group therefore cannot prevent a known
  strategy position from reaching the reduce-only end-of-day exit path.
- Existing protection is considered healthy only when both expected GTC OCA
  legs are active, use the same non-empty OCA group, and cover the full current
  position. A partial strategy-owned pair is cancelled and rebuilt; an
  unrelated active sell order fails closed instead of being cancelled.
- Each `intraday-momentum` run holds a non-blocking advisory lock for the
  complete position-check, decision, and order lifecycle. An overlapping run
  from any profile skips before connecting to IBKR instead of racing the first
  run over the same positions and order state. The accepted process has a hard
  60-second lifetime: a watchdog closes the lock and terminates the process
  with exit code `124` if it gets stuck. Intraday IBKR remote requests use a
  3-second request timeout and exit non-zero on failure. Other local strategy
  stages do not add separate deadlines; existing fill/cancel confirmation
  windows remain order-safety controls.
- A strategy-owned BUY order is expected to live only inside the one-shot run
  that submitted it. A later run treats any remaining `momentum-...-entry-...`
  BUY as orphaned, cancels it, and refuses to continue until IBKR confirms that
  no strategy entry remainder is active. The mandatory flatten path performs
  the same cleanup even when there is not yet a position.
- Position and OCA completeness are checked before the full quote/bar group is
  loaded. Missing protection is rebuilt from the entry state's persisted
  stop/take prices. A legacy entry without those fields receives a conservative
  fixed-percentage fallback, so a simultaneous signal-data outage cannot leave
  a known position unprotected.

The market data troubleshooting runbook is
[docs/ibkr-market-data-troubleshooting.md](docs/ibkr-market-data-troubleshooting.md).
It documents the previous failure mode where subscriptions were enabled but
the active Gateway session still needed a restart and fresh 2FA before live
quotes worked.

For a more active variant, use:

```bash
ibkr-bot intraday-momentum --profile high-frequency
```

The legacy semiconductor rotation preset is still available for comparison or
rollback with:

```bash
ibkr-bot intraday-momentum --profile rotation
ibkr-bot backtest-momentum --profile rotation
```

The default rotation setup rotates between `SOXL` and `SOXS` based on the
`QQQ` regime. The
old 7D/14D/30D numbers were overlapping diagnostics, not independent
validation, and are intentionally no longer presented as evidence of an edge.
The legacy `rotation` research parameters are:
`min_confirm_bars=1`, `min_trend_gap=0.001`, `min_vwap_gap=0.00025`,
`min_score=0.006`, `take_profit_pct=0.035`.

The current `rotation-hysteresis-v2` profile can be selected explicitly with:

```bash
ibkr-bot intraday-momentum --profile rotation-hysteresis-v2
ibkr-bot backtest-momentum --profile rotation-hysteresis-v2
```

Each live scan prints `core_decisions` first. For SOXL and SOXS it includes
the action/signal, entry status, available fast and slow EMA values, completed
bar count, bars still required, and the direct reason no entry was created.
An EMA remains `null` until its configured window is available. Benchmark and
full market-data diagnostics follow this core block.

V2 keeps the frozen V1 entries, risk budget, 0.60% stop, and 3.75% hard
take-profit. It adds a close-based profit lock: after a completed 5-minute
close reaches 3% above average cost, a 0.6% drawdown from the highest completed
post-entry close triggers the normal reduce-only software exit. V2 also stops
opening new positions at 13:30 America/New_York; positions already open keep
their normal stop, take-profit, profit-lock, reversal, and session-close exits.
The explicit `rotation-hysteresis-v1` profile and its `rotation-hysteresis`
compatibility alias remain available for rollback. See
[docs/strategy-baseline-v2.md](docs/strategy-baseline-v2.md).

In the 2025-07-10 through 2026-07-09 research run,
28 candidates were compared on 209 development sessions before opening a final
42-session holdout. The hysteresis profile improved the holdout net return from
3.52% to 8.74%, but two of four development blocks remained negative and a
double-cost development stress test remained negative. That evidence does not
establish a proven production edge; v1 remains available for rollback.

Backtest the same rule with a built-in transaction-cost model:

```bash
ibkr-bot backtest-momentum
```

The backtest mirrors the live exit split rather than treating every exit as a
close-based software decision. Broker-side protective stop and take-profit OCA
orders are evaluated against each completed bar's high/low after the entry
bar. Sell limits fill at their limit (or a better gap-open price), while sell
stops fill at their stop (or a worse gap-open price). If a five-minute bar
crosses both levels and tick ordering is unavailable, the stop is assumed to
fill first. Profit-lock, technical, and benchmark exits remain close-confirmed
and fill at the next bar open. Entry fills also remain next-bar-open estimates,
so venue-specific SMART price improvement cannot be reconstructed from OHLCV.

The tuning workflow used for this branch is documented in
[docs/backtest-parameter-tuning.md](docs/backtest-parameter-tuning.md).
The versioned parameters and change-control rules are documented in
[docs/strategy-baseline-v2.md](docs/strategy-baseline-v2.md), with the frozen
rollback baseline in [docs/strategy-baseline-v1.md](docs/strategy-baseline-v1.md).

### Historical Data Cache

Long intraday backtests persist every completed IBKR history page as daily
JSON files under `.ibkr_bot_data/historical/` by default:

Before any momentum backtest starts, a fail-closed historical-data preflight
checks that all strategy symbols and the benchmark share the same latest
session. It also verifies that the newest two sessions have aligned 5-minute
timelines and contain either 78 regular-session bars or 42 early-close bars.
Refresh missing history before retrying; the backtest will not silently run on
inconsistent or partial recent sessions. The scheduled daily refresh handles
whole-session cache staleness before this structural preflight runs.

```text
.ibkr_bot_data/historical/
├── 2026-07-08/
│   ├── QQQ__5_mins.json
│   ├── SOXL__5_mins.json
│   └── SOXS__5_mins.json
└── 2026-07-09/
    ├── QQQ__5_mins.json
    ├── SOXL__5_mins.json
    └── SOXS__5_mins.json
```

Overlapping pages are merged by timestamp, so retrying a download is safe.
The cache directory is ignored by git. To choose another location:

```bash
ibkr-bot backtest-momentum --data-dir /path/to/ibkr-history
```

To rerun from the daily files without connecting to IBKR, use the same
duration and cache directory with `--reuse-data`:

```bash
ibkr-bot backtest-momentum --duration "3 Y" --reuse-data
```

`--reuse-data` never refreshes the cache. Run once without that flag after a
new market session to download current bars and merge them into the daily
files. Keep the cache local: although it contains market data rather than
credentials, redistribution may be restricted by the data provider's terms.

### Backtest Calibration And Interpretation

Keep a backtest aligned with the live strategy before interpreting its return:

- Load the same `.env` used to define the live risk budget, then pass the same
  profile explicitly. In particular, match `--capital`, `--max-notional`, and
  `IBKR_MAX_RISK_PER_TRADE`; otherwise share counts can differ materially.
- Calibrate costs from actual execution reports. The default commission is
  `$1.00` per order, based on recent live IBKR fills of about `$1` on each side
  of a trade. A complete buy/sell trade therefore starts with about `$2` of
  fixed commission before spread and slippage. Override it when the account's
  realized commissions change.
- Keep spread and slippage enabled. A zero-cost run is useful only as a gross
  upper bound, not as an expected result.
- Use `--reuse-data` for reproducible comparisons after the daily cache has
  been refreshed. Record the first and last bar dates; a `60 D` request means
  60 calendar days and normally contains fewer trading sessions.
- Treat nested recent windows such as 30D and 60D as diagnostics, not
  independent validation. The 30D observations are contained in the 60D
  sample and do not provide a second confirmation of the strategy.
- Prefer the default chronological walk-forward report and untouched holdout
  for research conclusions. Do not tune parameters on the final holdout and
  then continue describing it as out-of-sample.
- Compare the simulator with live mechanics whenever execution code changes.
  The current engine enters and exits on the next bar open after a signal,
  evaluates stop/take conditions from bar closes, permits at most one completed
  trade per session, and liquidates any remaining position at the session end.

Example calibrated run using the live rotation profile and a `$4,000` order
budget:

```bash
set -a
source .env
set +a
ibkr-bot backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --capital 4000 \
  --max-notional 4000 \
  --commission-per-order 1.00 \
  --slippage-bps 1.0 \
  --spread-bps 1.0
```

To rerun against an already captured data set without contacting IBKR, append
`--reuse-data`. Confirm that the cache covers the intended end date before
comparing results.

By default the command builds one three-year data set using backward `1 W`
pages with explicit request end times (rather than an invalid monolithic
`3 Y`/`5 mins` request), runs chronological
252-day/63-day walk-forward folds, and reserves the final 63 trading days as a
fully untouched holdout. The parameters remain fixed: training ranges are
reported for provenance and are not silently optimized. The backtest models
commission, spread and slippage; entry and signal exits fill at the next bar's
open, and benchmark/asset bars are aligned by timestamp rather than array index.

Live entry size is capped by both notional and ATR risk:
`quantity <= IBKR_MAX_RISK_PER_TRADE / max(percent_stop, ATR * multiple)`.
The current live checkout sets `IBKR_MAX_RISK_PER_TRADE=120`; the committed
`.env.example` intentionally remains at the conservative `$10` setup default.
Filled entries receive broker-hosted GTC stop/take OCA orders. On restart, the
scanner queries active and completed IBKR orders by deterministic order ref,
rebuilds missing protection for an open position, and refuses duplicate entry
tasks. Order snapshots distinguish active, partial, filled, cancelled, and
rejected/inactive states.

The daily-entry state file is published with an atomic replacement. The live
scanner also checks filled IBKR entry order references for the current session,
so a process failure after a fill cannot silently reset the one-entry limit.

SOXL and SOXS are execution instruments with a daily 3x/-3x objective, not a
promise of three times the index's cumulative multi-day return. See the
[Direxion product disclosure](https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs).
The mandatory intraday flatten and risk cap are deliberate; for future signal
research, prefer an unleveraged semiconductor proxy such as SOXX or SMH and
keep the leveraged ETF confined to execution.

## Production Checklist

- Keep strategy code deterministic and test it without a broker connection.
- Keep paper trading on until market data, account, risk, and order-state handling are verified.
- Verify OCA behavior, partial fills, rejection handling, restart recovery, and
  end-of-day scheduling in the target paper account before enabling production.
- Add external alerting for disconnects, rejected orders, partial fills, and stale data.
- Run the bot under a process manager only after it can recover cleanly from TWS or Gateway restarts.
- For this host's IBC/Gateway keepalive setup, daily restart, Sunday cold restart, and 2FA retry notes, see [docs/ibc-gateway-startup.md](docs/ibc-gateway-startup.md).

## Tests

The risk tests use Python's standard library:

```bash
cd apps/ibkr-quant-bot
PYTHONPATH=src python -m unittest discover -s tests
```
