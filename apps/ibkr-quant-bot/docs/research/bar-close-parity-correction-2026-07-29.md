# Bar-Close Parity Correction - 2026-07-29

This note corrects a five-minute lookahead defect in the intraday backtest and
re-evaluates the V2, V3, and V4 rotation profiles. It is research and backtest
infrastructure work only. The running live checkout remains explicitly on V2.

## Root Cause

IBKR intraday bars are stamped at the start of their interval. A bar stamped
`11:55` contains trading from `11:55` through `12:00` and cannot be used by a
live strategy until `12:00`.

The former event loop treated the timestamp itself as signal availability.
It could therefore consume the complete `11:55` OHLC values at `11:55` and
fill from a later 30-second bar while still inside the five-minute interval.
That is lookahead, not a fill-model approximation.

The corrected event loop:

- keeps original IBKR timestamps on the bars passed to strategy code;
- schedules each signal event at `bar timestamp + signal bar duration`;
- uses only prefixes whose bars have completed by that event;
- fills from the first eligible execution bar at or after signal
  availability; and
- prevents same-session re-entry after an exit has marked the day closed.

The CLI now reports `signal_availability=bar-close`. A mixed-resolution
regression test proves that fill bars occurring before the signal bar close
cannot be selected.

## Fixed Evaluation Contract

- Code base: `origin/wt/codex-6` at `857feff`, plus the parity correction.
- Signal data: SMART five-minute bars from
  `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`.
- Fill data: SMART 30-second bars from
  `/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`.
- Sessions: 637, from 2024-01-10 through 2026-07-27.
- Preflight: 2026-07-24 and 2026-07-27, with 78 five-minute and 780
  30-second bars per symbol per full session.
- Capital: `$10,000`.
- Maximum notional: `$5,000`.
- Maximum risk per trade: `$120`.
- Costs: `$1` per order, `1` basis point slippage, and `1` basis point spread.
- Entry limit: one per session.
- Walk-forward: 252 provenance sessions, five non-overlapping 63-session OOS
  folds, and one final 63-session validation block.

## Corrected V2/V3/V4 Results

### Open-Pullback Execution Proxy

| Profile | Mean OOS | Minimum OOS | Positive folds | Final 63 sessions | Validation drawdown |
|---|---:|---:|---:|---:|---:|
| V2 | 2.50% | -3.61% | 3 / 5 | 14.11% | 4.18% |
| V3 immediate exit | 2.62% | -3.21% | 4 / 5 | 12.45% | 2.54% |
| V4 two-bar veto | 2.39% | -3.06% | 4 / 5 | 10.35% | 2.54% |

### Double Costs

| Profile | Mean OOS | Minimum OOS | Positive folds | Final 63 sessions | Validation drawdown |
|---|---:|---:|---:|---:|---:|
| V2 | 0.71% | -5.24% | 2 / 5 | 12.34% | 4.37% |
| V3 immediate exit | 0.93% | -4.83% | 3 / 5 | 10.58% | 2.73% |
| V4 two-bar veto | 0.78% | -4.62% | 3 / 5 | 8.46% | 2.73% |

### Worst-Case Execution

| Profile | Mean OOS | Minimum OOS | Positive folds | Final 63 sessions | Validation drawdown |
|---|---:|---:|---:|---:|---:|
| V2 | -4.56% | -8.17% | 0 / 5 | 1.77% | 4.96% |
| V3 immediate exit | -5.28% | -7.99% | 0 / 5 | -1.82% | 5.14% |
| V4 two-bar veto | -5.29% | -7.84% | 0 / 5 | -2.58% | 6.49% |

The parity correction materially reduces every earlier return estimate. V4 no
longer leads. V3 improves open-pullback fold consistency and validation
drawdown, but it does not establish a worst-case execution edge.

## 2026-07-28 Intraday Replay

The replay was refreshed from IBKR during the session and used only completed
bars through 13:15 America/New_York.

V4 first rejects the entry when the completed `11:55` bar fails its two-bar
momentum gate. At `12:05`, however, the completed `12:00` bar makes momentum
positive and V4 enters SOXL. It exits on the immediate reversal signal around
`12:25`.

- Open-pullback proxy: approximately `-$82.46`.
- Worst-case proxy: approximately `-$114.39`.
- Actual V2 gross fill loss: approximately `-$122.02`, before final
  commissions.

V4 therefore does not avoid the trade. Its useful behavior is the earlier
software exit, not the entry veto.

## Bounded Candidate Screening

The development folds screened:

- three- and four-bar positive momentum;
- warm-up windows from 31 through 36 bars;
- stronger confirmation counts;
- 1.2x long entry thresholds;
- a noon cutoff; and
- maximum selected-ETF intraday ranges of 8%, 10%, and 12%.

The noon cutoff avoided the event by eliminating all eligible baseline trades
and was rejected. Maximum-range gates avoided the event but reduced mean OOS
return to 1.73%-2.14%, below V3. Momentum and threshold changes still entered
the 2026-07-28 trade.

Warm-up values 32 and 33 improved development-fold mean return to 2.99% and
3.09%, but failed confirmation:

| Candidate | Mean OOS | Minimum OOS | Final 63 sessions | Worst-case final 63 |
|---|---:|---:|---:|---:|
| V3 min bars 32 | 2.99% | -1.97% | 8.34% | -4.19% |
| V3 min bars 33 | 3.09% | -1.97% | 7.19% | -4.27% |

They are rejected as unstable timing adjustments rather than retained
profiles.

## Decision

1. Ship the backtest bar-close parity correction before running or publishing
   another intraday comparison.
2. Withdraw the previous V3/V4 return tables.
3. Do not promote V4 to live trading.
4. Keep V2 as the current live contract.
5. If V3 is pursued, run it only as a shadow candidate. Its lower
   open-pullback drawdown is useful, but the worst-case folds do not support a
   real-money rollout.
6. Treat execution quality as a first-class dependency. None of the current
   profiles has a positive OOS mean under the deliberately pessimistic fill
   model.

Reproduce the bounded screening with:

```bash
PYTHONPATH=src python scripts/research-bar-close-rotation.py \
  --today-root /tmp/ibkr-v4-today-YYYYMMDD.XXXXXX
```

The `--today-root` input is optional and must contain separate `5m/` and
`30s/` SMART caches. Temporary intraday caches must not be committed.
