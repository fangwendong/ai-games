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
If quotes unexpectedly fall back to delayed data or the live strategy reports
that live quotes are unavailable, use
[docs/ibkr-market-data-troubleshooting.md](docs/ibkr-market-data-troubleshooting.md).
That runbook also documents how to enable real-time market data in IBKR Client
Portal and the required Market Data API acknowledgement.

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

Run the scanner and exit manager with:

```bash
ibkr-bot intraday-momentum
```

In live trading mode, the intraday scanners refuse delayed market data:

- Quote requests are forced through live market data instead of the generic
  `auto` fallback path.
- Historical bars must be fresh. By default the latest bar may be at most
  `IBKR_LIVE_BAR_MAX_AGE_SECONDS=420` seconds old, which allows normal
  completed 5-minute bars but rejects 15-20 minute delayed data.
- Strategy bars are restricted to the current New York regular session, so the
  opening signal cannot inherit the prior day's EMA or VWAP history.
- The scanner stops entering and liquidates positions during the final
  `IBKR_FLATTEN_BEFORE_CLOSE_MINUTES=10` minutes. Run the command on a schedule
  that includes this window; no software can flatten a position if it is not running.

The market data troubleshooting runbook is
[docs/ibkr-market-data-troubleshooting.md](docs/ibkr-market-data-troubleshooting.md).
It documents the previous failure mode where subscriptions were enabled but
the active Gateway session still needed a restart and fresh 2FA before live
quotes worked.

For a more active variant, use:

```bash
ibkr-bot intraday-momentum --profile high-frequency
```

The semiconductor rotation research preset is available with:

```bash
ibkr-bot intraday-momentum --profile rotation
ibkr-bot backtest-momentum --profile rotation
```

This preset rotates between `SOXL` and `SOXS` based on the `QQQ` regime. The
old 7D/14D/30D numbers were overlapping diagnostics, not independent
validation, and are intentionally no longer presented as evidence of an edge.
The current research parameters are:
`min_confirm_bars=1`, `min_trend_gap=0.001`, `min_vwap_gap=0.00025`,
`min_score=0.006`, `take_profit_pct=0.035`.

Backtest the same rule with a built-in transaction-cost model:

```bash
ibkr-bot backtest-momentum
```

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
Filled entries receive broker-hosted GTC stop/take OCA orders. On restart, the
scanner queries active and completed IBKR orders by deterministic order ref,
rebuilds missing protection for an open position, and refuses duplicate entry
tasks. Order snapshots distinguish active, partial, filled, cancelled, and
rejected/inactive states.

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
