# Recent-Regime Rotation Optimization - 2026-07-29

This note evaluates narrow changes to `rotation-hysteresis-v2` after the
2026-07-28 SOXL protective-stop exit. It is research, not the live contract.
The running live checkout remains on the explicitly selected V2 profile until
an operator approves a versioned rollout.

## Live Event Reconstruction

Sanitized broker execution data shows:

- SOXL entry: 27 shares at 12:00:05 America/New_York, average fill
  `113.439259`;
- broker-hosted stop: `109.15`;
- stop fill: all 27 shares at 12:31:00, average fill `108.92`;
- gross fill PnL: approximately `-$122.02`, before final round-trip
  commissions; and
- the paired take-profit order was cancelled by the OCA lifecycle.

The stop operated correctly. The failure was signal/exit behavior: QQQ still
qualified as bullish while SOXL had already reversed sharply. The first
post-entry 5-minute bar closed at `111.58`, and the current V2 exit hysteresis
required three confirmed reversal bars. The broker stop filled during the
12:30 bar before a later software exit could complete.

With exit hysteresis disabled, the same completed-bar state produces a
software exit after the 12:20 bar. A 5-minute next-open diagnostic uses
approximately `111.00` at 12:25, implying roughly `-$65.86` gross PnL and
about `$56` less loss than the actual protective-stop fill. This is a replay
estimate, not a claim about the price a live market order would have received.

## Fixed Research Contract

All comparisons use:

- signal bars: SMART 5-minute bars;
- fill bars: SMART 30-second bars;
- signal cache:
  `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`;
- fill cache:
  `/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`;
- data: 637 sessions from 2024-01-10 through 2026-07-27;
- latest preflight sessions: 2026-07-24 and 2026-07-27;
- 78 signal bars and 780 fill bars per symbol in each preflight session;
- capital: `$10,000`;
- maximum notional: `$5,000`;
- maximum risk per trade: `$120`;
- commission: `$1` per order;
- slippage: `1` basis point;
- spread: `1` basis point;
- maximum entries: one per session; and
- live-aligned entry proxy: `open-pullback`.

The walk-forward layout uses 252 training sessions for provenance, five
non-overlapping 63-session OOS folds, and a final 63-session validation block.
The final block is no longer described as untouched because this research
inspected it.

## First-Layer Screening

The first layer changed one family at a time.

| Candidate | Mean OOS return | Minimum OOS fold | Positive folds | Final 63-session return | Recent 20-session return |
|---|---:|---:|---:|---:|---:|
| V2 baseline | 7.56% | 2.44% | 5 / 5 | 20.81% | 12.55% |
| Disable exit hysteresis | 14.20% | 4.53% | 5 / 5 | 27.85% | 12.20% |
| Long thresholds 1.2x | 7.36% | 2.40% | 5 / 5 | 18.79% | 11.98% |
| Warm-up 36 bars | 5.75% | -0.58% | 4 / 5 | 9.81% | 4.86% |
| Entry cutoff 12:30 | 4.55% | 1.12% | 5 / 5 | 19.81% | 11.72% |

Changing the long confirmation count from one to two or three did not change
the trade set. The existing confirmation field counts closes above VWAP; it
does not detect the short-horizon failed breakout seen on 2026-07-28.

The screening rejects broader threshold tightening, later warm-up, and an
earlier global cutoff. Disabling exit hysteresis is the only tested existing
control that materially improves return and drawdown without increasing trade
count.

## Versioned Candidates

Two explicit, non-default profiles capture the useful mechanisms:

- `rotation-hysteresis-v3`: V2 with `use_exit_hysteresis=false`;
- `rotation-hysteresis-v4`: V3 plus a two-bar entry momentum veto.

The V4 veto requires the selected execution ETF's latest completed close to be
above its close two bars earlier. It applies symmetrically to SOXL and SOXS.
For the 2026-07-28 signal, SOXL's two-bar return was `-0.6751%`, so V4 would
have rejected the entry even though the slower EMA/VWAP score remained
bullish.

## Finalist Stress Results

| Scenario | Profile | Mean OOS return | Minimum OOS fold | Positive folds | Final 63-session return | Win / loss | Trade-level max drawdown |
|---|---|---:|---:|---:|---:|---:|---:|
| Live-aligned | V2 | 7.56% | 2.44% | 5 / 5 | 20.81% | 28 / 31 | 3.00% |
| Live-aligned | V3 | 14.20% | 4.53% | 5 / 5 | 27.85% | 42 / 17 | 0.61% |
| Live-aligned | V4 | 15.98% | 5.77% | 5 / 5 | 30.09% | 45 / 14 | 0.61% |
| Double costs | V2 | 5.71% | 0.70% | 5 / 5 | 18.92% | 28 / 31 | 3.19% |
| Double costs | V3 | 12.50% | 2.89% | 5 / 5 | 25.90% | 41 / 18 | 0.68% |
| Double costs | V4 | 14.35% | 4.21% | 5 / 5 | 28.14% | 43 / 16 | 0.68% |
| Worst-case fill | V2 | 0.83% | -3.28% | 2 / 5 | 12.18% | 26 / 33 | 2.97% |
| Worst-case fill | V3 | 7.24% | -0.02% | 4 / 5 | 19.63% | 35 / 24 | 1.12% |
| Worst-case fill | V4 | 9.39% | 1.40% | 5 / 5 | 20.74% | 35 / 24 | 1.12% |

The improvement comes from signal/exit logic. Signal and fill bar sizes,
costs, capital, sizing caps, and cache roots remain fixed within each
comparison.

## Decision

V3 is the primary production candidate. It is a one-toggle change, directly
addresses the realized loss mechanism, improves all five OOS folds, survives
double-cost and worst-case-fill stress, and does not add trades.

V4 is the stronger research candidate, but the two-bar veto was proposed after
inspecting the 2026-07-28 loss. Its historical consistency is encouraging but
does not make the current event independent evidence. Run V4 in shadow or
paper mode over new sessions before promoting it over V3.

Do not widen the stop to address this event. The ATR-based stop and `$120`
risk budget worked as designed; a wider stop would increase time exposed to a
broken signal. The higher-value change is to react to reversal earlier and,
after forward validation, veto entries whose selected ETF is already losing
short-horizon momentum.

## Reproduction

Run:

```bash
PYTHONPATH=src python scripts/research-recent-rotation.py
PYTHONPATH=src python scripts/research-rotation-finalists.py
```

Both scripts use cached data only and never connect to IBKR or place orders.
