# Live Backtest Non-Reconciliation Notes — 2026-07-19

This note records the main reasons the `rotation-hysteresis-v2` live execution
path and the current backtest output can still disagree, even after the latest
alignment work. It is a diagnostic note, not a new strategy proposal.

The important point is this: the strategy is not being judged on a pure
math-only backtest. It is being judged on a live execution contract that
includes SMART market-data freshness, one-entry-per-day behavior, protective
OCA handling, broker-side fills, end-of-day flattening, and a fixed live
capital basis. Any one of those can move the result.

## Current Comparison Contract

The only comparison that is meaningful for this branch is:

- strategy profile: `rotation-hysteresis-v2`
- signal bars: 5-minute SMART bars
- execution / fill proxy: 30-second bars
- fill model: `open-pullback`
- live capital basis: 4500 USD
- `max_notional`: 10000 USD
- `max_risk_per_trade`: 120 USD
- commission: 1 USD per order
- slippage / spread: 1 bps each

If any one of those changes, the result is no longer a direct live-vs-backtest
comparison. It becomes a different research experiment.

## Main Non-Reconciliation Sources

### 1. Exit handling is still more complex in live than in backtest

The backtest intentionally models protective stop and take-profit exits at the
bar level, but live trading also has:

- broker-hosted OCA state
- entry-fill-to-protection submission timing
- protection confirmation / repair
- partial fills and cancellation recovery
- end-of-day flatten logic

The backtest cannot reproduce the exact broker event order inside a completed
bar. That means on a day where both stop and take conditions exist inside the
same bar, the backtest must choose a conservative ordering. This is correct for
safety, but it is still an approximation.

Relevant implementation:

- `src/ibkr_quant_bot/backtest.py`
- `src/ibkr_quant_bot/strategy.py`

### 2. `min_bars=30` and `trend_window=34` are not fully aligned

The live profile starts making decisions once 30 completed bars exist, but the
trend EMA window is 34. That means bars 30-33 use a clamped EMA helper rather
than a fully mature 34-bar history. The live audit already flagged this as an
internal inconsistency.

This does not mean the strategy is broken. It does mean the earliest part of
each session is mathematically softer than the later part of the same session,
and backtest comparisons should not pretend otherwise.

Relevant note:

- `docs/live/live-strategy-audit-2026-07-17.md`

### 3. Signal bars and fill bars serve different jobs

The 5-minute bars drive the signal. The 30-second bars are a fill proxy. The
1-minute bars are only a diagnostic path.

If the backtest uses 1-minute or 30-second bars to re-run the signal logic, it
is no longer testing the live strategy. It is testing a different strategy with
different effective timing and different EMA/trend/VWAP dynamics.

Relevant note:

- `docs/data/historical-market-data.md`

### 4. Historical data completeness changes the answer more than people expect

Long intraday backtests are only trustworthy when the history root is complete
for all three symbols and the benchmark, with aligned timelines and no split or
session drift. If one symbol is missing a chunk, the month-level result can look
like:

- zero trades
- zero return
- suspiciously low trade count
- a month that looks “too good” or “too bad” for no strategy reason

The preflight checks exist specifically to prevent that, but the cache still has
to be rebuilt when corporate actions or missing days are discovered.

### 5. Capital scaling is not linear in the metrics people usually read

The live strategy now uses a fixed 4500 USD capital basis. That changes dollar
PnL, but it does not necessarily change trade cadence. If you compare a 4500
USD live run to a 20000 USD research run, the raw dollars will diverge even when
the strategy logic is identical.

The right comparison is:

- win rate
- trade count
- exit reason distribution
- per-trade return
- monthly return rate

Not absolute PnL alone.

### 6. `QQQ` is a regime input, not a second strategy

The benchmark is part of the signal contract. If QQQ is missing, stale, or
inconsistent with SOXL/SOXS, the result can change sharply because the strategy
is not just trading the ETFs in isolation.

This is especially important when the benchmark decides whether only SOXL or
only SOXS is eligible.

### 7. Protective exits are more conservative in backtest by design

The current backtest makes the conservative choice when it cannot know the
intrabar ordering. That is the right thing for safety, but it biases the result
against the strategy in some fast bars and toward the stop in ambiguous bars.

This means the backtest is useful for relative comparison, but not for claiming
that a single day’s fill was exact.

## What To Trust

Trust the following first:

- whether the strategy entered at all
- whether the exit reason is consistent with the signal state
- whether the fill model used the correct 30-second proxy
- whether the timeline was complete and source-consistent
- whether monthly return patterns are stable under the same contract

Trust the following less:

- exact dollar PnL on a single day
- exact fill price on a stop/take day
- one-month performance without a completeness audit

## What To Fix Before Any New Research Claim

1. Keep the live contract frozen.
2. Keep signal bars on 5 minutes.
3. Keep fill bars on 30 seconds.
4. Keep `capital=4500`, `max_notional=10000`, `max_risk_per_trade=120`.
5. Rebuild history if QQQ / SOXL / SOXS data is missing or split-affected.
6. Compare per-day trade logs against live before changing parameters.
7. Treat `trend_window=34` vs `min_bars=30` as a separate structural issue.

## Bottom Line

The backtest is not “wrong” in a single way. The non-reconciliation comes from
three layers:

1. live execution has broker behavior that OHLC backtests cannot fully express;
2. the strategy has a small internal warm-up inconsistency;
3. data completeness and capital normalization can dominate the headline result.

If a future backtest run still disagrees after those three layers are held
constant, then the remaining gap is worth treating as a real strategy defect
rather than a reporting artifact.
