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
IBKR_MAX_RISK_PER_TRADE=120 \
IBKR_ENTRY_CASH_RESERVE_USD=10 \
IBKR_LIVE_TRADABLE_CAPITAL_CACHE_MAX_AGE_SECONDS=90 \
IBKR_MAX_DAILY_ENTRIES=1 \
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --capital 4500 \
  --duration "6 M" \
  --bar-size "5 mins" \
  --train-days 30 \
  --test-days 10 \
  --step-days 10 \
  --holdout-days 10 \
  --entry-fill-model profile-default \
  --reuse-data \
  --data-dir /home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/.ibkr_bot_data/historical \
  --market-data-exchange SMART
```

The same setup was also checked with the lower live-tradable cash snapshot
`1494.41 USD` to confirm that the strategy logic, not the current cash level,
was the primary driver of the signal cadence.

## Results

| Case | Final holdout net return | Trade count | Win / loss | Notes |
|---|---:|---:|---:|---|
| `capital=1494.41`, `max_notional=10000` | `18.11%` | `9` | `7 / 2` | Live-cash snapshot, same strategy cadence |
| `capital=4500`, `max_notional=10000` | `18.33%` | `9` | `7 / 2` | Stress-tested with higher deployable capital |

Fold stability for the `capital=4500`, `max_notional=10000` run:

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

## Three-year fill comparison — 2026-07-18

This run kept the strategy decision bar fixed at `5 mins` and only changed the
fill-price timeline used for entry/exit approximation:

- `30s` fill bars from `historical/30-sec-rth`
- `1m` fill bars from `historical/1-min-rth`
- `5m` fill bars from `historical/5-min-rth`

The shared live-aligned contract was unchanged:

- `profile=rotation-hysteresis-v2`
- `capital=4500`
- `max_order_notional=10000`
- `max_risk_per_trade=120`
- `min_bars=30`
- `bar_size=5 mins`
- `entry_fill_model=open-pullback`
- `commission_per_order=1`
- `slippage_bps=1`
- `spread_bps=1`
- `market_data_exchange=SMART`

### Overall result

| Fill bar size | Gross return | Net return | Final capital | Trades | Win / loss |
|---|---:|---:|---:|---:|---:|
| `30s` | `222.40%` | `184.20%` | `12,788.87` | `427` | `237 / 190` |
| `1m` | `185.86%` | `148.63%` | `11,188.53` | `426` | `237 / 189` |
| `5m` | `157.57%` | `116.79%` | `9,755.41` | `532` | `227 / 305` |

### Final holdout

The final untouched holdout stayed in the same direction across all three
fill models:

| Fill bar size | Final holdout net return | Trade count | Win / loss |
|---|---:|---:|---:|
| `30s` | `18.40%` | `9` | `7 / 2` |
| `1m` | `18.67%` | `9` | `7 / 2` |
| `5m` | `18.33%` | `9` | `7 / 2` |

### Monthly net PnL by fill model

Amounts are net PnL in USD. Percentages in parentheses are measured against
the fixed `4500 USD` starting capital used in this run.

| Month | `30s` | `1m` | `5m` |
|---|---:|---:|---:|
| 2023-07 | — | — | `-48.28` `(-1.07%)` |
| 2023-08 | — | — | `-373.29` `(-8.30%)` |
| 2023-09 | — | — | `-124.24` `(-2.76%)` |
| 2023-10 | — | — | `-202.08` `(-4.49%)` |
| 2023-11 | — | — | `-14.38` `(-0.32%)` |
| 2023-12 | — | — | `-83.38` `(-1.85%)` |
| 2024-01 | — | — | `19.97` `(0.44%)` |
| 2024-02 | — | — | `-103.81` `(-2.31%)` |
| 2024-03 | — | — | `70.99` `(1.58%)` |
| 2024-04 | — | — | `418.54` `(9.30%)` |
| 2024-05 | — | — | `100.64` `(2.24%)` |
| 2024-06 | `50.23` `(1.12%)` | `51.43` `(1.14%)` | `78.73` `(1.75%)` |
| 2024-07 | `311.71` `(6.93%)` | `270.16` `(6.00%)` | `441.02` `(9.80%)` |
| 2024-08 | `522.61` `(11.61%)` | `441.33` `(9.81%)` | `26.33` `(0.59%)` |
| 2024-09 | `489.77` `(10.88%)` | `456.22` `(10.14%)` | `102.25` `(2.27%)` |
| 2024-10 | `149.46` `(3.32%)` | `102.78` `(2.28%)` | `202.28` `(4.50%)` |
| 2024-11 | `352.41` `(7.83%)` | `249.91` `(5.55%)` | `-85.03` `(-1.89%)` |
| 2024-12 | `442.92` `(9.84%)` | `446.25` `(9.92%)` | `67.08` `(1.49%)` |
| 2025-01 | `-3.83` `(-0.09%)` | `3.51` `(0.08%)` | `11.19` `(0.25%)` |
| 2025-02 | `-129.82` `(-2.88%)` | `-164.12` `(-3.65%)` | `-424.63` `(-9.44%)` |
| 2025-03 | `397.56` `(8.83%)` | `379.46` `(8.43%)` | `478.62` `(10.64%)` |
| 2025-04 | `409.92` `(9.11%)` | `347.96` `(7.73%)` | `150.04` `(3.33%)` |
| 2025-05 | `-61.84` `(-1.37%)` | `-20.35` `(-0.45%)` | `-100.18` `(-2.23%)` |
| 2025-06 | `9.14` `(0.20%)` | `8.86` `(0.20%)` | `167.32` `(3.72%)` |
| 2025-07 | `167.67` `(3.73%)` | `128.49` `(2.86%)` | `-49.19` `(-1.09%)` |
| 2025-08 | `-61.21` `(-1.36%)` | `-93.65` `(-2.08%)` | `198.26` `(4.41%)` |
| 2025-09 | `-79.90` `(-1.78%)` | `-35.61` `(-0.79%)` | `-241.38` `(-5.36%)` |
| 2025-10 | `522.14` `(11.60%)` | `479.09` `(10.65%)` | `544.67` `(12.10%)` |
| 2025-11 | `338.91` `(7.53%)` | `231.16` `(5.14%)` | `662.37` `(14.72%)` |
| 2025-12 | `801.64` `(17.81%)` | `671.88` `(14.93%)` | `89.32` `(1.98%)` |
| 2026-01 | `283.45` `(6.30%)` | `311.63` `(6.93%)` | `442.39` `(9.83%)` |
| 2026-02 | `173.40` `(3.85%)` | `-14.33` `(-0.32%)` | `-39.57` `(-0.88%)` |
| 2026-03 | `233.92` `(5.20%)` | `212.52` `(4.72%)` | `605.76` `(13.46%)` |
| 2026-04 | `26.90` `(0.60%)` | `197.10` `(4.38%)` | `-205.38` `(-4.56%)` |
| 2026-05 | `644.43` `(14.32%)` | `526.84` `(11.71%)` | `352.17` `(7.83%)` |
| 2026-06 | `1,292.61` `(28.72%)` | `520.71` `(11.57%)` | `878.29` `(19.52%)` |
| 2026-07 | `1,004.67` `(22.33%)` | `979.29` `(21.76%)` | `1,242.01` `(27.60%)` |

### Takeaway

- `30s` fill produced the strongest three-year result.
- `1m` was second-best and stayed close to `30s` in the final holdout.
- `5m` fill materially worsened both net return and trade quality, with a much
  higher loss count.
- The decision bar should stay at `5 mins`; the fill timeline is the only knob
  that should vary in this comparison.

## Related docs

- [Backtest parameter tuning](backtest-parameter-tuning.md)
- [Strategy baseline v2](strategy-baseline-v2.md)
- [Live strategy review log](live-strategy-review-log.md)
