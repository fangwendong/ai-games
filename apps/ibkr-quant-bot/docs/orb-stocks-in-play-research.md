# Stocks-in-Play ORB Research

This document describes the isolated research path for a long-only opening
range breakout (ORB) strategy. It is not a live-trading profile.

## Isolation Boundary

The research strategy does not import, extend, or modify
`rotation-hysteresis-v2`. It has its own:

- implementation: `src/ibkr_quant_bot/orb_research.py`
- configurations: `config/orb-stocks-in-play-v1.json` and
  `config/orb-stocks-in-play-v2-research.json`
- local data root: `<worktree>/.ibkr_bot_data/orb-research/historical`
- strategy version: `orb-stocks-in-play-v1-research`

It reuses only the generic historical-cache reader, bar model, and transaction
cost model. It has no order-submission command and no runtime state directory.

## Data Refresh

All worktrees share the canonical data-disk cache at
`/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`. Download, read, audit,
and incremental-refresh procedures are documented in
[historical-market-data.md](historical-market-data.md). Generated cache files
are ignored by Git.

Use a read-only, dry-run Gateway connection. Keep the fetch single-worker and
CPU constrained because two years of five-minute history requires many paged
IBKR requests.

```bash
cd apps/ibkr-quant-bot
set -a
source /path/to/safe/.env
set +a
export IBKR_READONLY=true
export IBKR_DRY_RUN=true
export IBKR_ALLOW_LIVE_TRADING=false
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONPATH=src

nice -n 10 taskset -c 0 python -m ibkr_quant_bot.cli refresh-history \
  --symbols NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
            BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL \
            CRWD NBIS MARA QQQ \
  --duration "2 Y" \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

IBKR pagination writes each page through `save_bars_by_day`, so completed
pages remain available if a later request fails. Rerunning the command merges
and de-duplicates bars by timestamp.

## Backtest

```bash
cd apps/ibkr-quant-bot
PYTHONPATH=src python -m ibkr_quant_bot.orb_research \
  --config config/orb-stocks-in-play-v1.json \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --chronological-split
```

The baseline research rules are deliberately narrow:

- long-only
- first five-minute range
- 14-session opening-volume RVOL, minimum 1.0
- prior 14-session average daily volume of at least one million shares
- prior 14-session ATR of at least USD 0.50
- bullish opening range
- top three candidates by RVOL
- close-confirmed breakout, filled at the next bar open
- no entries after 15:30 America/New_York in the paper-like baseline; earlier
  cutoffs may be compared as predeclared execution variants
- stop signal based on 0.1 times prior ATR, filled at the next bar open
- exit signal at 15:50, filled at the next bar open when available
- at most one trade per session
- USD 4,000 notional cap and USD 120 risk cap
- USD 1 commission per side plus one basis point of slippage and one basis
  point of quoted spread

The close-confirmed, next-bar-fill convention is more conservative than using
the breakout bar's high or the stop bar's low as an executable price.

## July 2026 Research Result

The first fixed baseline failed across the two-year sample. Starting with USD
4,000, its full-sample return was -35.37% over 437 trades. Train and validation
returns were -20.61% and -16.88%, respectively.

The limited structural search tested longer opening ranges, earlier entry
cutoffs, wider ATR stops, stricter RVOL ranking, and a QQQ opening-regime
filter. The least fragile exploratory candidate is recorded in
`orb-stocks-in-play-v2-research.json`:

- 15-minute opening range
- no entries after 11:00 America/New_York
- 0.5 times prior 14-session ATR stop distance
- opening RVOL of at least 1.25
- only the highest-RVOL eligible stock per session
- QQQ must have a bullish first 15-minute range

Its chronological results, including the configured costs, were:

| Period | Dates | Trades | Win rate | Net return | Max drawdown |
|---|---|---:|---:|---:|---:|
| Train | 2024-08-02 to 2025-10-01 | 74 | 48.65% | +23.54% | USD 614.56 |
| Validation | 2025-10-02 to 2026-02-20 | 19 | 63.16% | +5.92% | USD 257.11 |
| Holdout | 2026-02-23 to 2026-07-14 | 25 | 32.00% | -16.12% | USD 644.77 |
| Full | 2024-08-02 to 2026-07-14 | 118 | 47.46% | +13.07% | USD 686.94 |

The holdout sign reversal means this candidate fails the promotion gate. Keep
it research-only; do not add a live profile or scheduler. Since the holdout has
now been inspected, further variants on this same data are exploratory and
require a new forward paper-trading period before any promotion decision.

The fixed universe was selected from currently liquid stocks, so this pilot
also has universe-selection and survivorship bias. A production-grade test
would reconstruct a point-in-time daily universe rather than reuse today's
symbol list over the full history.

The data audit found no split-sized discontinuity for LCID even though LCID
completed a 1-for-10 reverse split in 2025; IBKR's cached history is
split-adjusted across that boundary. NBIS had one greater-than-50% overnight
move on 2025-09-09. That move coincided with its announced Microsoft
infrastructure agreement and is an event gap, not an unadjusted split. Keep
event gaps in the research data, but retain the anomaly scan before reruns.

## Validation Discipline

Use chronological train, validation, and untouched holdout periods. Do not
change parameters after inspecting the holdout result. A candidate must have:

- positive net results after the configured costs in train and validation
- no sign reversal in the untouched holdout
- adequate trade count across multiple market regimes
- acceptable closed-equity drawdown
- no dependence on one symbol or one event cluster

Do not add a live profile, scheduler, order reference, or state directory until
the research candidate passes these checks and then survives paper trading.
