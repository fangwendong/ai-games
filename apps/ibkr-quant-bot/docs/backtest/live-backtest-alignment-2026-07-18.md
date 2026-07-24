# Live Backtest Alignment Notes — 2026-07-18

This note records the backtest alignment work for `rotation-hysteresis-v2`.
It is a working reference for the live-trading checkout and the research
checkout. The goal is not to invent new parameters; the goal is to make the
backtest output use the same live-facing contract and to keep the report
readable.

## What was aligned

- Use the same strategy profile as live: `rotation-hysteresis-v2`
- Keep the market-data source fixed to `SMART`
- Resolve the v2 entry model through `profile-default`
  - `rotation-hysteresis-v2` resolves to `open-pullback`
- Keep the live-style capital controls visible in the report:
  - `max_notional`
  - `max_risk_per_trade`
  - `entry_cash_reserve_usd`
  - `max_daily_entries`
  - `live_tradable_capital_cache_max_age_seconds`
- Print a `core_parameters` block at the top of every `backtest-momentum`
  report so the first thing in the JSON is the run contract, not the fold
  results

## Why the default cap was raised

The old `max_order_notional=1000` default was too small for the current live
rotation profile and could truncate sizing before the strategy logic was
really exercised. That made the backtest look artificially constrained.

The default was raised to `10000` so the notional cap stops acting as the
binding constraint in ordinary live-aligned runs. The strategy still obeys its
own `max_risk_per_trade` sizing rule.

## Walk-forward settings used in the current 6-month cache

The standard walk-forward defaults are still:

- `train_days=252`
- `test_days=63`
- `step_days=63`
- `holdout_days=63`

Those settings require at least 378 trading sessions. A 6-month cache does not
have that many sessions, so the live-aligned calibration used a shorter
chronological split:

- `train_days=30`
- `test_days=10`
- `step_days=10`
- `holdout_days=10`

That keeps the fold ordering chronological while matching the available cache
length.

## Current calibration runs

The calibration used the cached SMART historical bars and the v2 live profile.
The command form was:

```bash
IBKR_MAX_ORDER_NOTIONAL=10000 \
IBKR_MAX_RISK_PER_TRADE=300 \
IBKR_ENTRY_CASH_RESERVE_USD=10 \
IBKR_LIVE_TRADABLE_CAPITAL_CACHE_MAX_AGE_SECONDS=90 \
IBKR_MAX_DAILY_ENTRIES=1 \
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --capital 10000 \
  --duration "6 M" \
  --bar-size "5 mins" \
  --train-days 30 \
  --test-days 10 \
  --step-days 10 \
  --holdout-days 10 \
  --entry-fill-model profile-default \
  --reuse-data \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --fill-data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth \
  --market-data-exchange SMART
```

The same setup was also checked with the lower live-tradable cash snapshot
`1494.41 USD` to confirm that the strategy logic, not the current cash level,
was the primary driver of the signal cadence.

After the fill-resolution comparison settled, the default live-aligned fill
proxy moved to 30-second bars. The 1-minute fill cache remains useful for
diagnostics, but 30-second fill is the baseline for future live-vs-backtest
comparisons.

## Results

| Case | Final holdout net return | Trade count | Win / loss | Notes |
|---|---:|---:|---:|---|
| `capital=1494.41`, `max_notional=10000` | `18.11%` | `9` | `7 / 2` | Live-cash snapshot, same strategy cadence |
| `capital=10000`, `max_notional=10000` | `18.33%` | `9` | `7 / 2` | Stress-tested with higher deployable capital |

Fold stability for the `capital=10000`, `max_notional=10000` run:

- base profile: 4 / 4 positive OOS folds
- mean OOS return: `2.9747%`
- final holdout remains consistent with the OOS direction

The parameter-sensitivity check remained positive across the three variants:

- lenient `0.8x`
- base
- strict `1.2x`

## Conclusions

- The backtest output now surfaces the core run contract before the result
  blocks, which makes each run easier to compare against live execution.
- Raising `max_order_notional` to `10000` removed an artificial sizing cap.
- The v2 profile still shows positive walk-forward behavior under the current
  live-aligned assumptions.
- Higher starting capital changes dollar PnL more than it changes trade cadence;
  the entry/exit logic is still the dominant factor.
- For the current strategy, 30-second fill bars are the recommended default
  when comparing backtest behavior against live execution. Use 1-minute fill
  only when you want a coarse sensitivity check.

## Current Live Contract Snapshot

Keep the live checkout aligned with this exact configuration unless the same
commit updates the documentation and code together:

- Strategy profile: `rotation-hysteresis-v2`
- Symbols allowed by live risk checks: `SOXL,SOXS,QQQ`
- Strategy instruments: `SOXL` long, `SOXS` short, `QQQ` benchmark
- `IBKR_MAX_ORDER_NOTIONAL=10000`
- `IBKR_MAX_RISK_PER_TRADE=300`
- `IBKR_LIVE_TRADABLE_CAPITAL_USD=10000`
- `IBKR_ENTRY_CASH_RESERVE_USD=10`
- `IBKR_MAX_DAILY_ENTRIES=1`
- Signal bars: `5 mins`
- Fill bars: `30 secs`
- Quote cache: `100` samples per symbol, refreshed every `1` second
- Quote cache freshness: `3` seconds

## Related docs

- [Backtest parameter tuning](backtest-parameter-tuning.md)
- [Strategy baseline v2](../strategy/strategy-baseline-v2.md)
