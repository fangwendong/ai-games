# IBKR Quant Bot

Python scaffold for connecting to Interactive Brokers market data and trading APIs through TWS or IB Gateway.

This project is intentionally guarded:

- `IBKR_READONLY=true` is the default, so broker connections are read-only unless explicitly changed.
- Paper trading port `7497` is the default.
- `IBKR_DRY_RUN=true` is the default, so validated orders are not sent.
- Live mode requires both `IBKR_TRADING_MODE=live` and `IBKR_ALLOW_LIVE_TRADING=true`.
- Every order is checked against `IBKR_ALLOWED_SYMBOLS` and `IBKR_MAX_ORDER_NOTIONAL`.

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

## Commands

Check configuration and dependency status:

```bash
ibkr-bot doctor
```

### Read-Only Live Gateway Queries

For a logged-in live IB Gateway, the common API port is `4001`. Keep `IBKR_READONLY=true` for balance, position, and quote checks:

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

## Production Checklist

- Keep strategy code deterministic and test it without a broker connection.
- Keep paper trading on until market data, account, risk, and order-state handling are verified.
- Add position-aware risk controls before any live use.
- Add structured logs and alerting for disconnects, rejected orders, partial fills, and stale data.
- Run the bot under a process manager only after it can recover cleanly from TWS or Gateway restarts.

## Tests

The risk tests use Python's standard library:

```bash
cd apps/ibkr-quant-bot
PYTHONPATH=src python -m unittest discover -s tests
```
