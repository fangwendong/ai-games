# Gap Reversion Research

This document records an isolated, research-only long gap-down reversion
strategy. It is not a live profile and has no order-submission path, scheduler,
or runtime state.

Academic work has documented overnight-to-intraday reversal in US equities,
including a stronger opening reversal after negative overnight returns. That
is the economic hypothesis behind this candidate. The implementation adds
confirmation and actual transaction costs instead of assuming that every gap
can be faded at the opening print.

## Isolation And Reproduction

- implementation: `src/ibkr_quant_bot/gap_reversion_research.py`
- configuration: `config/gap-reversion-v1-research.json`
- shared data: `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`
- strategy version: `gap-reversion-v1-research`

Run the fixed configuration with:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.gap_reversion_research \
  --config config/gap-reversion-v1-research.json \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --chronological-split
```

## Fixed Candidate

- current liquid-stock research universe, with its documented survivorship
  and universe-selection limitation
- prior 14-session volume and ATR statistics only
- opening gap down of at least 4% and at least 0.4 prior ATR
- prior average daily volume of at least five million shares
- price of at least USD 10
- ignore days when QQQ gaps down more than 1.5%
- rank by gap size in ATR units and consider only the most extreme stock
- observe at least 15 minutes
- first-15-minute relative volume no greater than 4, to reject likely
  information-driven repricing events
- require two consecutive bullish, rising closes and a close above session
  VWAP
- fill at the next five-minute bar open, no later than 10:15 New York time
- target the previous close, stop at 0.5 prior ATR, and flatten by the close
- at most one position per day
- USD 4,000 capital and notional cap, USD 120 risk cap
- USD 1 commission per side, one basis point slippage, and one basis point
  spread per side

All entry and exit signals use completed bars and fill at the next bar open.

## Comparison With Live V2

The benchmark is the frozen `rotation-hysteresis-v2` profile run on the same
cache, capital, risk budget, and cost model. The dates below exactly match its
two non-overlapping tests and final 63-session holdout.

| Period | Gap reversion | Live v2 | Gap trades | Gap win rate |
|---|---:|---:|---:|---:|
| 2025-07-17 to 2025-10-14 | +8.33% | +3.00% | 9 | 55.56% |
| 2025-10-15 to 2026-01-14 | +4.84% | +11.35% | 6 | 66.67% |
| 2026-04-14 to 2026-07-14 | +6.29% | +30.83% | 8 | 62.50% |

The gap strategy returned +22.46% over the full 2024-07-15 through 2026-07-14
window, with 43 trades, a 62.79% win rate, and USD 207.23 closed-equity maximum
drawdown. It did not beat v2 consistently and failed the replacement goal in
the final comparison period. Keep it research-only.

The original baseline's holdout was inspected before the limited structural
search. The selected candidate was chosen using train and validation results,
but the final result must still be treated as exploratory rather than a fresh
independent statistical test. A new forward paper period is required before
reconsidering it.

The 10:15 entry cutoff was explored after the first 11:00 hybrid holdout had
already been inspected. It improved the historical hybrid comparison, but it
is explicitly post-holdout research and must be frozen for a new forward test.

## Promotion Gate

Do not add a live profile merely because this strategy diversifies v2 or has a
positive full-sample return. Promotion requires a new forward period in which
it beats the frozen v2 benchmark after costs without larger risk, survives
symbol and event concentration review, and retains positive non-overlapping
segments.
