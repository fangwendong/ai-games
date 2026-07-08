# IBKR Trading Bot Skeleton

This is a conservative Python skeleton for IBKR robot trading. It is designed to start with Paper Trading and dry-run execution, then gradually graduate to real paper orders after connection, order status, and risk controls are verified.

It is not investment advice and it does not include a profitable strategy. The goal is trading infrastructure: connection checks, strategy interface, risk gates, execution adapter, order audit logs, and notifications.

Maintenance notes for future agents live in [`agents.md`](agents.md).
The low-risk default strategy is documented in [`docs/volatility_managed_trend.md`](docs/volatility_managed_trend.md).
The monthly rotation variant is documented in [`docs/quality_low_vol_rotation.md`](docs/quality_low_vol_rotation.md).
The weekly momentum variant is documented in [`docs/weekly_momentum_rotation.md`](docs/weekly_momentum_rotation.md).
The tech / semiconductor rotation variant is documented in [`docs/tech_semiconductor_rotation.md`](docs/tech_semiconductor_rotation.md).
The daily short-term momentum variant is documented in [`docs/short_term_momentum_rotation.md`](docs/short_term_momentum_rotation.md).
The 5-minute intraday scan is documented in [`docs/five_minute_momentum.md`](docs/five_minute_momentum.md).

## What Is Included

- `ib_insync` based IB Gateway / TWS adapter
- Paper-first configuration with live trading disabled by default
- Strategy interface plus a small moving-average crossover example and a low-risk volatility-managed trend strategy
- Monthly quality-plus-low-volatility rotation for small accounts
- Weekly momentum rotation with a market filter
- Tech / semiconductor rotation with a broad-market filter
- Daily short-term momentum rotation for liquid ETFs
- 5-minute intraday momentum scan for liquid ETFs
- Risk manager for notional limits, position limits, order frequency, daily loss, and market-order blocking
- SQLite audit log for signals, orders, fills, and risk events
- CLI commands for DB initialization, connection checks, live quotes, strategy scans, and one dry-run strategy pass
- Unit tests for the risk layer and strategy behavior

## Setup

```bash
cd ibkr-bot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Configure IB Gateway or TWS:

1. Log in to Paper Trading.
2. Enable API socket access.
3. Use a paper port such as `4002` for IB Gateway or `7497` for TWS, depending on your setup.
4. Add `127.0.0.1` as a trusted IP if required.

## Commands

```bash
ibkr-bot init-db
ibkr-bot check-connection
ibkr-bot account
ibkr-bot balance
ibkr-bot positions
ibkr-bot quote --symbol SPY
ibkr-bot scan
ibkr-bot scan --strategy quality_low_vol_rotation
ibkr-bot scan --strategy five_minute_momentum
ibkr-bot rebalance
ibkr-bot backtest --duration '3 Y'
ibkr-bot backtest --strategy weekly_momentum_rotation --duration '1 Y'
ibkr-bot backtest --strategy tech_semiconductor_rotation --duration '1 Y' --capital 3000 --profile weekly
ibkr-bot trade-once --symbol SPY
ibkr-bot run-once --symbol SPY
ibkr-bot backtest --strategy short_term_momentum_rotation --duration '1 Y'
ibkr-bot scan --strategy five_minute_momentum --duration '2 D' --bar-size '5 mins'
```

`account` shows the raw account summary rows from IBKR. `balance` filters that summary down to the main cash, net liquidation, buying power, margin, and PnL fields. `positions` shows the open holdings with quantity, average cost, and notional value.

`quote` fetches the current snapshot for one symbol. `scan` walks the configured symbol list, records the signal history, and prints the current strategy verdict for each symbol. `trade-once` runs one strategy evaluation, applies risk checks, and optionally submits an order.

The default strategy is `volatility_managed_trend`. It is long-only, uses a long moving-average trend filter, and stays out of the market when the recent realized volatility is above a fixed cap. That makes it easier to keep the bot conservative for a small account. You can switch back to the moving-average demo with `--strategy moving_average_cross`.

The rotation model is `quality_low_vol_rotation`. It ranks an automatic liquid ETF catalog using a trailing window plus volatility, drawdown, consistency, and a minimum average volume filter, then rotates into the top symbol or moves to cash when nothing clears the filters. Set `IBKR_ROTATION_SYMBOLS` only if you want to override the built-in catalog.

`backtest` runs the rotation model over historical daily bars from IBKR and prints return, CAGR, volatility, drawdown, and trade count. The default profile is monthly, but it can be switched to daily with `--profile daily` or to the small-account low-turnover preset with `--profile low_turnover`.

`weekly_momentum_rotation` is the intermediate option. It rebalances weekly, keeps a broader momentum tilt, and uses a market filter so it can step aside when the broad market weakens.

`tech_semiconductor_rotation` is the tech-focused variant. It rotates among `QQQ`, `XLK`, `IYW`, `SMH`, and `SOXX`, and keeps the semiconductor sleeve small by design.

You can switch the rebalance cadence with `--profile monthly|daily|low_turnover` or override it directly with `--rebalance-frequency monthly|weekly|daily`. Explicit `--lookback`, `--volatility-window`, `--volume-window`, `--min-trailing-return`, `--max-annualized-volatility`, and `--switch-score-margin` values always win over the preset.

`short_term_momentum_rotation` is the daily option. It ranks liquid ETFs by 30-bar relative strength and stays in cash when nothing clears the threshold.

`five_minute_momentum` is the intraday validation path. It checks 5-minute bars, uses short/slow moving averages plus volume confirmation, and is meant for scanning rather than rapid order-churning. The scan prints a ranked list of the strongest intraday candidates, so you can validate the structure even when nothing is ready to trade.

`vwap_pullback` is the more selective intraday mean-reversion variant. It waits for a VWAP reclaim after a real pullback, asks for stronger volume confirmation, and uses tighter exit rules so the backtest does less churn on a small account.

If you want to sanity-check overfitting on intraday strategies, pass `--validation-split 0.7` to `ibkr-bot backtest` and it will print separate in-sample and out-of-sample summaries.

Extended-hours support is opt-in through `IBKR_ALLOW_EXTENDED_HOURS=true`. When enabled, the broker sets `outsideRth=True` and the risk gate keeps extended-hours trading on limit orders only.

`run-once` stays as a compatibility alias for `trade-once`. It remains in dry-run mode unless `IBKR_DRY_RUN=false`. Live trading is also blocked unless `IBKR_ALLOW_LIVE=true`, and the default `.env.example` does not allow it.

## Suggested Rollout

1. Run `check-connection` until account, positions, and current time are stable.
2. Run `run-once` in dry-run mode and confirm risk decisions and audit rows.
3. Allow paper orders only after you inspect generated orders.
4. Keep paper automation running for several weeks before considering small live exposure.

## Headless Server Deployment

Deployment notes for a Debian server without a physical GUI live in `deploy/headless/`. The tested pattern is to install IB Gateway and IBC under `/home/fwd/ibkr`, install only `xvfb` as a system package, and keep the bot connected to `127.0.0.1:4002`.
