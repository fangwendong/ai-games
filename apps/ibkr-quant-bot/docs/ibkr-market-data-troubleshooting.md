# IBKR Market Data Troubleshooting Runbook

This runbook captures the real-time market data issue seen on this host and
the working fix. It is written for future AI agents and maintainers who need to
diagnose why the live strategy cannot obtain real-time quotes even though the
IBKR account appears to have market data enabled.

Do not paste IBKR usernames, account IDs, session tokens, or full Gateway logs
into commits. Keep examples generic.

## What Happened

The account owner had enabled the relevant IBKR market data subscription, but
the bot still could not obtain live quotes through IB Gateway. The live strategy
refused to run because it requires real-time data and must not silently use
delayed quotes.

After restarting IB Gateway through IBC and completing IBKR Mobile 2FA, live
quotes started working again. Verification returned live bid/ask/last values
for symbols such as `AAPL`, `SOXL`, and `SPY`.

Practical conclusion: an active subscription is necessary but not sufficient.
The currently logged-in IB Gateway session may still be stale or not fully
entitled until Gateway is restarted and reauthenticated.

## How To Enable Real-Time Market Data

Use the IBKR Client Portal. IBKR's current documentation says market data
subscriptions are managed from Settings under Trading Platform, and API users
must also enable the Market Data API acknowledgement.

Official references:

- IBKR Campus API market data subscriptions:
  <https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/>
- IBKR Client Portal market data subscription guide:
  <https://www.ibkrguides.com/orgportal/usersettings/marketdatasubscriptions.htm>
- IBKR Campus lesson on subscribing to data:
  <https://www.interactivebrokers.com/campus/trading-lessons/subscribing-to-data/>
- IBKR Market Data Assistant:
  <https://www.ibkrguides.com/clientportal/marketdataassistant.htm>

Steps:

1. Log in to IBKR Client Portal with the live account. Demo accounts cannot
   subscribe to paid market data. Do not use paper-only login for this task.
2. Open the user menu in the upper-right corner and select `Settings`.
3. Under `Trading Platform`, open `Market Data Subscriptions`.
4. Complete or verify `Market Data Subscriber Status` and the
   non-professional/professional questionnaire. Exchanges charge different
   prices based on this status.
5. Open the subscriptions configuration with the gear icon.
6. Select the market data package that covers the exact product and exchange.
   For US-listed stocks and ETFs, use IBKR's `Market Data Assistant` if unsure:
   enter the symbol, instrument type, and exchange, then subscribe to the
   package it recommends for live top-of-book data.
7. Review the price and confirm the subscription. IBKR notes that market data
   subscriptions are generally not prorated for the month, so mid-month
   subscriptions may still charge the full monthly fee shown in Client Portal.
8. Back on the `Market Data Subscriptions` page, find
   `Market Data API Acknowledgement`.
9. Click the gear icon for that acknowledgement and set API market data access
   to `Yes`.
10. Save/continue until Client Portal confirms the changes.
11. Restart IB Gateway or TWS and complete IBKR Mobile 2FA. If Gateway was
    already logged in before the subscription or API acknowledgement was
    changed, the active API session may not pick up the new entitlement until
    a fresh login.
12. Verify through the bot with forced live quotes:

```bash
cd /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot
set -a
source .env
set +a
export PYTHONPATH=src
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4001
export IBKR_TRADING_MODE=live
export IBKR_READONLY=true
export IBKR_DRY_RUN=true
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SOXL
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SPY
```

Successful live quotes should return current `bid`, `ask`, or `last`. If the
forced `live` check still returns empty values, do not run the live strategy.

Minimum account requirements and available packages can change. If a future AI
agent is unsure which subscription covers a symbol, use IBKR's official Market
Data Assistant instead of guessing.

## What We Learned About Subscriptions

This section records this incident's practical subscription findings, not a
complete IBKR product catalog.

The current strategy needs live API data for US-listed ETFs/stocks such as
`SOXL`, `SOXS`, `QQQ`, `SPY`, and manual test symbols such as `AAPL`. The bot
uses streaming-style API requests and fresh 5-minute bars, so snapshot-only
access is not enough.

What we saw in Client Portal:

- The account already had complimentary items such as
  `US Real-Time Non Consolidated Streaming Quotes`.
- The account also showed `Market Data Snapshot Counter` with zero estimated
  cost. That counter is not a streaming subscription and should not be treated
  as sufficient for this live strategy.
- The relevant paid item shown in the UI was
  `US Equity and Options Add-On Streaming Bundle` for non-professional users.
  In the UI description, it provides top-of-book data for NYSE Network A,
  AMEX/ARCA Network B, NASDAQ Network C, and OPRA.
- That add-on said it requires
  `US Securities Snapshot and Futures Value Bundle (NP)` first.
- The combined cost discussed in the incident was about USD 14.50/month:
  USD 10.00 for `US Securities Snapshot and Futures Value Bundle` plus
  USD 4.50 for `US Equity and Options Add-On Streaming Bundle`.

Practical answer from this incident:

1. Keep/enable the free `US Real-Time Non Consolidated Streaming Quotes`, but
   do not assume it is enough for robust strategy execution.
2. If full API top-of-book coverage is required for the current ETF strategy,
   subscribe to `US Securities Snapshot and Futures Value Bundle (NP)` and then
   `US Equity and Options Add-On Streaming Bundle (NP)`.
3. Enable `Market Data API Acknowledgement = Yes`.
4. Restart IB Gateway/TWS after changing subscriptions or acknowledgement.
5. Verify with forced live API calls before running the strategy.

Do not use only `Market Data Snapshot Counter` or only the snapshot bundle as
the strategy's solution. The strategy needs current streaming/fresh data, and
we specifically rejected delayed or stale data in live mode.

If the traded symbols change, rerun IBKR Market Data Assistant for the new
symbols instead of assuming the same bundle is still correct.

## Symptoms

Typical symptoms:

- `ibkr-bot quote SYMBOL` only returns delayed or close-like values.
- `IbkrBroker.live_quote()` raises:

```text
live quote unavailable for SYMBOL; refusing to use delayed data
```

- The live strategy refuses to trade because it cannot get a live quote.
- Account pages or screenshots show market data permissions are enabled, but
  the local API session still behaves as if live data is unavailable.

Do not treat a successful historical bar request as proof of live quote access.
Historical bars and streaming/snapshot market data are different IBKR API
paths.

## Data Modes In This Bot

`IBKR_MARKET_DATA_TYPE` controls the requested TWS API market data type:

| Value | TWS API data type | Use |
|---|---:|---|
| `live` | 1 | Real-time data only |
| `frozen` | 2 | Frozen last market data |
| `delayed` | 3 | Delayed data |
| `delayed_frozen` | 4 | Delayed frozen data |
| `auto` | live, then delayed fallback | Convenient manual quote checks only |

Important behavior:

- `ibkr-bot quote` may use `auto`, which tries live first and falls back to
  delayed if live data is unavailable.
- `ibkr-bot intraday-momentum` uses `live_quote()` in live trading mode and
  refuses delayed data.
- Live historical bars must also pass freshness checks. The default
  `IBKR_LIVE_BAR_MAX_AGE_SECONDS=420` allows normal completed 5-minute bars but
  rejects delayed bars that are typically 15-20 minutes stale.

## Quick Diagnosis

Run from the bot directory with the live Gateway port:

```bash
cd /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot
set -a
source .env
set +a
export PYTHONPATH=src
export IBKR_HOST=127.0.0.1
export IBKR_PORT=4001
export IBKR_TRADING_MODE=live
export IBKR_READONLY=true
export IBKR_DRY_RUN=true
```

Check Gateway connectivity:

```bash
python3 -m ibkr_quant_bot.cli doctor
ss -ltnp | grep -E '4001|4002|7496|7497'
```

Check whether generic quotes work:

```bash
IBKR_MARKET_DATA_TYPE=auto python3 -m ibkr_quant_bot.cli quote SOXL
IBKR_MARKET_DATA_TYPE=auto python3 -m ibkr_quant_bot.cli quote SPY
```

Then force live quotes. This is the important test for live trading:

```bash
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SOXL
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SPY
```

If `auto` returns data but forced `live` returns empty bid/ask/last, the bot is
probably seeing delayed or fallback data. Do not run the live strategy.

## Working Fix

Restart IB Gateway through IBC and approve 2FA.

Stop old Gateway/IBC processes:

```bash
pkill -f 'ibcalpha.ibc.IbcGateway'
pkill -f 'ibcstart.sh'
```

Confirm the API port is closed:

```bash
ss -ltnp | grep -E '4001|4002|7496|7497' || true
```

Start Gateway again:

```bash
export DISPLAY=:1
/opt/ibc/gatewaystart.sh
```

Approve the IBKR Mobile 2FA prompt. Wait until Gateway is fully logged in and
listening on port `4001`:

```bash
ss -ltnp | grep 4001
```

Then rerun the forced live quote checks:

```bash
cd /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot
set -a
source .env
set +a
export PYTHONPATH=src
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SOXL
IBKR_MARKET_DATA_TYPE=live python3 -m ibkr_quant_bot.cli quote SPY
```

Successful live quotes should include at least one of `bid`, `ask`, or `last`
with a current market value. During regular trading hours, bid/ask are the most
useful proof.

## Entitlement Checklist

If restart does not fix live quotes, check these items before changing code:

1. The account is logged into the correct live account, not paper.
2. The subscription covers the relevant exchange and instrument. For US stocks
   and ETFs, NASDAQ/NYSE/ARCA access may matter depending on the symbol and
   quote route.
3. The account has accepted required market data agreements.
4. The subscription is active for the current month and not pending approval.
5. The account is not already consuming the same market data from another
   session in a way that violates IBKR limits.
6. Gateway completed login after the subscription was enabled. If the
   subscription was changed while Gateway was already logged in, restart
   Gateway.
7. `Market Data API Acknowledgement` is enabled in Client Portal. IBKR API
   requests can still fail even when normal platform market data is visible if
   the API acknowledgement has not been accepted.

## Delayed Data Is Not Acceptable For Live Strategy

The live strategy must not use delayed data:

- Delayed quotes may be 15-20 minutes behind.
- The strategy trades 5-minute bars and intraday momentum, so delayed input can
  produce stale entries and exits.
- The code intentionally raises an error from `live_quote()` instead of falling
  back to delayed data.

Use delayed data only for manual diagnostics or non-trading experiments:

```bash
IBKR_MARKET_DATA_TYPE=delayed python3 -m ibkr_quant_bot.cli quote SOXL
```

## Historical Bars vs Snapshot Quotes

Do not confuse these:

- Historical bars: `reqHistoricalData`, used by backtests and trend/bar logic.
- Live quote: `reqMktData` with market data type `live`, used by live trading
  to confirm current price and reject delayed market data.

It is possible for historical bars to be returned while live quotes are empty
or delayed. For live trading, both quote availability and bar freshness matter.

### Standalone Bounded Live Quote Cache

Run one read-only process that subscribes to QQQ, SOXL, and SOXS concurrently:

```bash
IBKR_READONLY=true \
IBKR_DRY_RUN=true \
IBKR_ALLOW_LIVE_TRADING=false \
IBKR_MARKET_DATA_TYPE=live \
PYTHONPATH=src python -m ibkr_quant_bot.cli stream-live-quotes
```

The process keeps a `deque(maxlen=100)` for each symbol, so the default
three-symbol profile retains at most 300 samples in memory. It atomically
replaces `live-quotes.json` every second; readers therefore see either the old
complete file or the new complete file, never a partial write. Configure it
with `IBKR_LIVE_QUOTE_CACHE_PATH`,
`IBKR_LIVE_QUOTE_CACHE_REFRESH_SECONDS`, and
`IBKR_LIVE_QUOTE_MAX_SAMPLES_PER_SYMBOL`.

Each scheduled strategy poll reads the newest sample for all three symbols
without waiting. Every symbol must be present, carry a bid, ask, or last value,
and be no older than `IBKR_LIVE_QUOTE_CACHE_MAX_AGE_SECONDS` (three seconds by
default). If the file is missing, malformed, incomplete, or stale, the strategy
requests one concurrent live SMART snapshot group through `reqTickers`; this
fallback has no fixed `sleep`. If that complete group is unavailable, the
strategy fails closed. The streaming process cancels every subscription in a
`finally` block when it exits and reconnects after transient Gateway or network
failures. Strategy output records `live_quote_source=cache` or
`live_quote_source=snapshot` so operators can confirm which path was used.

## SMART To ARCA Failover

ARCA failover is an explicit, disabled-by-default safety feature controlled by
`IBKR_ARCA_FALLBACK_ENABLED`. Quotes for QQQ, SOXL, and SOXS must first pass as
one complete SMART group. The strategy then loads and validates the three bar
series from SMART. If any bar series fails, it discards the entire SMART bar
attempt and retries the complete bar group on ARCA. Quotes and order routing
remain SMART.

The selected exchange is persisted for the trading date under
`.ibkr_bot_state/market-data-source-YYYY-MM-DD.json`. Every later poll must use
that pinned bar source. It does not switch bar sources during the session. If
the complete SMART quote group or both candidate bar groups fail validation,
the strategy fails closed and does not submit an order.

Backtests used to approve this behavior must generate signals from a cache
carrying the same bar-source metadata. See `docs/historical-market-data.md`;
do not compare an ARCA-bar live decision with a SMART-bar historical result.

## Code Paths To Inspect

Relevant files:

- `src/ibkr_quant_bot/broker.py`
  - `_set_market_data_type()`
  - `quote()`
  - `live_quote()`
  - `live_quote_snapshots()`
  - `stream_live_quotes()`
  - `historical_bars()`
- `src/ibkr_quant_bot/quote_cache.py`
  - `QuoteCacheWriter`
  - `load_fresh_quotes()`
- `src/ibkr_quant_bot/cli.py`
  - `intraday-momentum`
  - live data freshness checks
- `src/ibkr_quant_bot/config.py`
  - `IBKR_MARKET_DATA_TYPE`
  - `IBKR_LIVE_BAR_MAX_AGE_SECONDS`

If a future AI agent sees missing live data, inspect these code paths only
after checking Gateway login state, market data type, and entitlements.

## Known Good Post-Fix State

After the successful restart:

- Gateway was running through IBC on port `4001`.
- IBKR Mobile 2FA had been approved.
- Forced live quote requests returned current bid/ask/last values for multiple
  liquid symbols.
- The live strategy could proceed past the market data guard.

This does not prove every symbol has live entitlement. Recheck any newly traded
symbol with forced `IBKR_MARKET_DATA_TYPE=live` before relying on it.
