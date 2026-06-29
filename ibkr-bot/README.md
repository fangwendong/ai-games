# IBKR Trading Bot Skeleton

This is a conservative Python skeleton for IBKR robot trading. It is designed to start with Paper Trading and dry-run execution, then gradually graduate to real paper orders after connection, order status, and risk controls are verified.

It is not investment advice and it does not include a profitable strategy. The goal is trading infrastructure: connection checks, strategy interface, risk gates, execution adapter, order audit logs, and notifications.

## What Is Included

- `ib_insync` based IB Gateway / TWS adapter
- Paper-first configuration with live trading disabled by default
- Strategy interface plus a small moving-average crossover example
- Risk manager for notional limits, position limits, order frequency, daily loss, and market-order blocking
- SQLite audit log for signals, orders, fills, and risk events
- CLI commands for DB initialization, connection checks, and one dry-run strategy pass
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
ibkr-bot run-once --symbol SPY
```

`run-once` stays in dry-run mode unless `IBKR_DRY_RUN=false`. Live trading is also blocked unless `IBKR_ALLOW_LIVE=true`, and the default `.env.example` does not allow it.

## Suggested Rollout

1. Run `check-connection` until account, positions, and current time are stable.
2. Run `run-once` in dry-run mode and confirm risk decisions and audit rows.
3. Allow paper orders only after you inspect generated orders.
4. Keep paper automation running for several weeks before considering small live exposure.

## Headless Server Deployment

Deployment notes for a Debian server without a physical GUI live in `deploy/headless/`. The tested pattern is to install IB Gateway and IBC under `/home/fwd/ibkr`, install only `xvfb` as a system package, and keep the bot connected to `127.0.0.1:4002`.
