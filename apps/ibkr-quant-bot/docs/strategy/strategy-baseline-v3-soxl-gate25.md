# Strategy Baseline V3 With SOXL Chop Gate

`rotation-hysteresis-v3-soxl-gate25` is the live profile adopted on
2026-07-29. It keeps the frozen V2 entry, sizing, protective-order, profit-lock,
entry-cutoff, and QQQ regime contract, uses V3 immediate technical exits, and
adds one causal entry-only chop veto.

## Entry Chop Veto

The veto uses completed five-minute `SOXL` bars from the current New York
regular session:

- reference symbol: `SOXL`
- observation window: the first 30 completed bars
- first possible evaluation: 12:00 America/New_York
- displacement: absolute difference between the first bar open and bar 30 close
- range: highest high minus lowest low across those same 30 bars
- gate ratio: `displacement / range`
- minimum passing ratio: `0.25`

When the ratio is below `0.25`, the session is treated as directionless and all
new `SOXL` and `SOXS` entries are vetoed for the rest of that session. Later
bars cannot turn the gate back on. Missing, incomplete, or zero-range reference
data fails closed for a potential entry.

The gate never exits an existing position and never changes protective orders.
QQQ remains the regime benchmark; SOXL is only the chop reference.

## Exit Contract

This profile inherits V3's `use_exit_hysteresis=false`. Technical and benchmark
exit signals therefore act on the first completed-bar confirmation. Protective
stop/take orders, the close-based profit lock, and mandatory end-of-day flatten
remain unchanged from V2.

## Operational Contract

- signal bars: SMART five-minute regular-session bars
- fill research: SMART 30-second regular-session bars
- live quotes: forced live SMART data
- maximum risk per trade: resolved from `IBKR_MAX_RISK_PER_TRADE`
- current production risk budget: 120 USD
- current configured principal cap: 10,000 USD
- entry cash reserve: 10 USD
- one daily entry maximum remains enforced

The explicit rollback profiles remain:

- `rotation-hysteresis-v2`
- `rotation-hysteresis-v3`
- `rotation-hysteresis-v1`

## Promotion Evidence

The promotion run on 2026-07-29 used refreshed SMART caches through
2026-07-28, 10,000 USD initial capital, 5,000 USD maximum notional, 120 USD
maximum risk per trade, 1 USD commission per order, 1 bp slippage, and 1 bp
spread. Signal availability was bar close; fills used separate 30-second bars.

Chronological fixed-parameter evaluation used 252 training days, 63 test days,
63-day non-overlapping steps, five development OOS folds, and a final 63-day
holdout:

| Fill/cost case | Mean OOS | Worst OOS | Positive folds | Final holdout |
|---|---:|---:|---:|---:|
| Open-pullback, standard costs | 3.06% | -1.29% | 4/5 | 13.91% |
| Open-pullback, double costs | 1.82% | -2.44% | 3/5 | 12.58% |
| Worst-case fill, standard costs | -2.42% | -4.37% | 0/5 | 2.97% |

The newest 126 sessions returned 19.33% with 322.68 USD closed-trade
drawdown under the standard model, 16.69% under double costs, and 1.68% under
the worst-case fill model. The newest 10 sessions returned 3.44%, 3.27%, and
0.82%, respectively.

These are conditional historical results, not proof of future edge. The base
candidate's descriptive OOS p-value was about 0.063 before multiple-testing
correction and about 0.190 after Bonferroni correction. Preserve the rollback
profiles and monitor live drift.

## Validation

Use the canonical SMART caches and keep signal/fill roots separate:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v3-soxl-gate25 \
  --duration "930 D" \
  --bar-size "5 mins" \
  --fill-bar-size "30 secs" \
  --fill-data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth \
  --reuse-data \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --capital 10000 \
  --max-notional 5000 \
  --commission-per-order 1 \
  --slippage-bps 1 \
  --spread-bps 1
```
