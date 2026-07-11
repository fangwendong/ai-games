# Backtest Parameter Tuning

This document captures the tuning loop used for the semiconductor rotation
strategy in `ibkr-quant-bot`. The goal is to make parameter changes
reproducible and to avoid optimizing against the final holdout window.

## Core rule

Tune against a fixed, chronological walk-forward split:

- keep the data set fixed
- keep the transaction-cost model fixed
- keep the final holdout untouched until the end
- compare candidate parameter sets on the same folds

The backtest command supports cached daily bars so the same input can be reused
without reconnecting to IBKR:

```bash
ibkr-bot backtest-momentum --duration "120 D" --data-dir .ibkr_bot_data/historical
ibkr-bot backtest-momentum --duration "120 D" --reuse-data --data-dir .ibkr_bot_data/historical
```

## What to measure

Do not judge a candidate only by raw net return percentage on the walk-forward
report. For this strategy, the more useful comparison is:

- absolute net profit
- profit normalized by deployable capital, for example `net_profit / 4000`
- OOS fold consistency
- trade count and win/loss balance
- how much of the result is consumed by commission, spread, and slippage

That normalization matters because a small backtest capital base can make a good
percentage return look larger than it would be on the actual deployable budget.

## Tuning order

Adjust one layer at a time, in this order:

1. Entry filters
2. Exit logic
3. Sizing / risk budget

Within each layer, keep the rest of the strategy fixed.

For the current rotation profile, the most relevant knobs are:

- `min_bars`
- `long_min_confirm_bars` / `short_min_confirm_bars`
- `long_min_trend_gap` / `short_min_trend_gap`
- `long_min_vwap_gap` / `short_min_vwap_gap`
- `long_min_score` / `short_min_score`
- `benchmark_exit_confirm_bars`
- `max_risk_per_trade`
- `max_notional`

## Decision rule

A candidate is only worth keeping if it improves the deployable-capital-normalized
result without making the OOS folds fragile.

Reject a change if it does any of the following:

- raises trade count but lowers `net_profit / capital`
- looks better only on the final holdout
- improves the mean while making one of the OOS folds materially worse
- adds cost faster than it adds gross edge

## What the recent tests showed

The recent rotation-hysteresis sweeps produced a few useful lessons:

- `max_risk_per_trade` helped up to about `60`, then flattened out.
- `min_bars=30` was better than lower values in the recent sample.
- loosening entry filters did not improve `net_profit / capital`; it mostly
  added noise.
- reducing `benchmark_exit_confirm_bars` from `3` to `1` improved the profit
  normalized by capital a little, but it also made the OOS profile less stable.
- allowing multiple trades per day increased turnover, but the extra activity
  was mostly eaten by costs.

Treat those as observations from the current sample, not as permanent truths.

## Practical workflow

1. Freeze the live-ish baseline you want to test.
2. Run the chronological backtest with cached data.
3. Change one family of parameters.
4. Compare the deployable-capital-normalized result.
5. Check OOS fold stability.
6. Only then decide whether to keep the change.

If you are comparing two candidates and one only wins by adding a lot more
trading activity, prefer the one with the cleaner OOS profile unless the
improvement is large enough to justify the additional turnover.
