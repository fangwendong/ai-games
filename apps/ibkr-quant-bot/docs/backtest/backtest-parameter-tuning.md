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

## Current live-aligned backtest contract

When the goal is to mirror `rotation-hysteresis-v2`, do not invent a separate
research profile. Use the same live-facing sizing and exit contract that the
live runner prints.

The current contract is:

- `profile=rotation-hysteresis-v2`
- `capital=10000`
- `max_order_notional=10000`
- `max_risk_per_trade=300`
- `min_bars=30`
- `entry_fill_model=profile-default` (resolved to `open-pullback` for v2)
- `fill_bar_size=30 secs`
- `fill_data_dir=/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`
- `commission_per_order=1`
- `slippage_bps=1`
- `spread_bps=1`
- `bar_size=5 mins`
- `market_data_exchange=SMART`

If any of those drift, the run is not a strict live comparison. Label it as a
research variant and do not compare it directly against live execution.

For the current v2 tuning path, use 30-second fill bars as the default
execution proxy. Keep the 1-minute fill cache only for diagnostics and
comparison runs. Use 5-minute bars for signal logic only.

The backtest command supports cached daily bars so the same input can be reused
without reconnecting to IBKR:

```bash
ibkr-bot backtest-momentum --duration "120 D" --data-dir .ibkr_bot_data/historical
ibkr-bot backtest-momentum --duration "120 D" --reuse-data --data-dir .ibkr_bot_data/historical
```

## Mandatory historical-data preflight

Do not start a backtest until recent history has been refreshed and validated.
This is a correctness requirement, not an optional troubleshooting step.

Use this order for every run:

1. Refresh `SOXL`, `SOXS`, and `QQQ` from IBKR into the daily cache. The
   refresh is timestamp-merged and is safe to repeat.
2. Confirm that all three symbols have the same latest completed New York
   trading session.
3. Validate the newest two common sessions before calculating any strategy
   result.
4. Only after the preflight passes, select the requested trailing trading
   sessions and run the backtest.

The CLI enforces steps 2 and 3. For each of the newest two sessions it requires:

- identical 5-minute timestamps across `SOXL`, `SOXS`, and `QQQ`
- no duplicate timestamps
- exactly five minutes between adjacent bars
- 78 bars for a normal 09:30-16:00 session, or 42 bars for a standard
  09:30-13:00 early close

Any mismatch fails closed before the walk-forward or holdout calculation. Do
not bypass the failure by deleting the latest date or shortening the requested
window. Refresh the affected symbols, check the IBKR trading calendar for an
early close, and rerun the preflight.

For past dates, use `IbkrBroker.historical_market_sessions()` to obtain the
regular-session schedule. It calls IBKR's dedicated `reqHistoricalSchedule`
API with `useRTH=True`. Do not use `market_session()` for historical cache
validation: that live guard reads contract `liquidHours`, which may omit past
dates even when valid bars exist. Validate each cached timeline against the
historical session's open-inclusive, close-exclusive 5-minute grid; this also
handles early-close days without hard-coding a date.

An online `backtest-momentum` run requests history from IBKR and merges it into
the cache before this validation. A `--reuse-data` run never downloads data; it
only validates what is already on disk. Therefore the scheduled post-close
refresh remains necessary even though the structural preflight is built into
the command. The production schedule refreshes on Beijing time Tuesday through
Saturday at 06:30, after the preceding US regular session has closed.

The scheduled job runs a fixed command instead of generating an ad-hoc
validator:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli refresh-history
```

Run it with `IBKR_READONLY=true`, `IBKR_DRY_RUN=true`, and
`IBKR_ALLOW_LIVE_TRADING=false`. An empty HMDS response for one refresh request
does not by itself invalidate an existing cache. The command keeps previously
merged bars and then fails closed unless every symbol contains the complete
latest IBKR historical session and the preceding session.

When reporting a result, always include:

- the first and last trading-session dates actually used
- the number of trading sessions, not just a calendar-day label
- the newest two sessions checked by the preflight and their bar counts
- whether data came from a fresh IBKR request or `--reuse-data`

For example, after the 2026-07-13 refresh the preflight should report both
2026-07-10 and 2026-07-13 with 78 bars for each of the three symbols. This
example is illustrative; agents must inspect the current cache rather than
hard-code these dates.

## Live-aligned execution model

The default intraday backtest models the two live exit paths separately:

- broker-side protective stop/take OCA orders may fill intrabar after the
  entry bar; stop gaps receive the worse opening price and take-profit gaps
  receive opening price improvement
- if one five-minute bar reaches both protective prices, the stop fills first
  because OHLCV does not reveal tick ordering
- software profit-lock, technical-reversal, and benchmark exits require a
  completed bar and fill at the next bar open
- entries use a bar-level marketable-limit approximation. The v2 live profile
  defaults to an open-to-low pullback model so fills can benefit from intrabar
  price improvement when the signal bar trades below the opening print. You can
  still force the older next-bar-open proxy with `--entry-fill-model
  next-bar-open` when you want a strict historical baseline. SMART routing or
  dark-pool improvement is not inferable from historical five-minute bars and
  remains represented only by the configured spread/slippage assumptions.

Protective prices are calculated from the modeled entry fill and only the bars
that were complete when the entry signal fired. Do not use the entry bar's
full high/low to trigger protection because part of that bar predates the live
fill. This convention is intentionally conservative when both protective
levels trade in the same bar and avoids tuning a favorable tick sequence from
OHLCV data.

Execution-model changes invalidate direct comparisons with reports generated
under the former all-close-confirmed exit model. Rerun every baseline and
candidate on the same code revision before comparing parameters.

## What to measure

Do not judge a candidate only by raw net return percentage on the walk-forward
report. For this strategy, the more useful comparison is:

- absolute net profit
- profit normalized by deployable capital, for example `net_profit / 10000`
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

- `max_risk_per_trade` helped up to about `60` in the older tuning sample.
  The current live-aligned v2 contract uses `300` to remove an artificial
  sizing cap while keeping the resolved risk budget visible in the report.
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
2. Refresh and pass the mandatory historical-data preflight.
3. Run the chronological backtest with cached data.
4. Change one family of parameters.
5. Compare the deployable-capital-normalized result.
6. Check OOS fold stability.
7. Only then decide whether to keep the change.

If you are comparing two candidates and one only wins by adding a lot more
trading activity, prefer the one with the cleaner OOS profile unless the
improvement is large enough to justify the additional turnover.

For the most recent live-aligned calibration run, including the `core_parameters`
report shape and the 2026-07-18 conclusions, see
[live-backtest-alignment-2026-07-18.md](live-backtest-alignment-2026-07-18.md).
