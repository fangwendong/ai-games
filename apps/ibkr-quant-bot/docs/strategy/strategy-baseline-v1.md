# Frozen Live Strategy Baseline V1

`rotation-hysteresis-v1` is the frozen live signal baseline as of 2026-07-12.
It exists to stop repeated optimization on already inspected historical data.

V1 remains the rollback profile after `rotation-hysteresis-v2` was adopted on
2026-07-14. V2 is documented in [strategy-baseline-v2.md](strategy-baseline-v2.md).

## Frozen Signal Definition

| Group | Parameter | Value |
|---|---|---:|
| Instruments | Execution symbols | `SOXL`, `SOXS` |
| Instruments | Regime benchmark | `QQQ` |
| Data | Bar size | 5 minutes |
| Data | Minimum bars | 30 |
| Trend | Fast / slow / regime EMA | 13 / 21 / 34 |
| Trend | Trend lookback | 5 bars |
| Benchmark | Fast / slow / lookback | 13 / 21 / 5 |
| Long entry | Confirm bars | 1 |
| Long entry | Trend / VWAP / score minimum | 0.10% / 0.025% / 0.60% |
| Short entry | Confirm bars | 2 |
| Short entry | Trend / VWAP / score minimum | 0.15% / 0.025% / 0.60% |
| Risk exit | Percent stop | 0.60% |
| Risk exit | ATR window / multiple | 14 / 2.0 |
| Profit exit | Fixed take profit | 3.75% |
| Signal exit | Technical / benchmark confirmation | 3 / 3 bars |
| Signal exit | Reversal votes | 2 |

The strategy also requires VWAP and QQQ benchmark confirmation, permits one
entry per session, trades regular/liquid hours only, and flattens ten minutes
before the IBKR-reported session close.

The exact machine-readable parameters live in
`FROZEN_ROTATION_HYSTERESIS_PARAMETERS` in `cli.py`. Tests compare every field
against the constructed strategy. The frozen profile rejects a benchmark
override instead of silently changing the baseline.

## Frozen Deployment Envelope

The current live deployment uses:

- maximum risk per trade: USD 120;
- maximum order notional: USD 4,000;
- maximum entries per session: 1; and
- transaction-cost calibration: USD 1 commission per order plus 1 bp slippage
  and 1 bp spread in the standard backtest.

Risk and notional affect position size, not signal selection. They may be
reduced for safety without claiming a new edge. Do not increase them based on
the already inspected backtest history.

## Change Control

Do not modify this profile in place to improve historical results. A proposed
signal change must:

1. use a new profile and version name;
2. leave this baseline available for comparison;
3. state the hypothesis before examining new results;
4. run in research or shadow mode without changing live orders; and
5. be evaluated on newly accumulated, non-overlapping forward data.

Bug fixes, broker calendar checks, corporate-action guards, order idempotency,
monitoring, and cost calibration from actual fills are not signal-parameter
changes. They still require tests and must not weaken safety checks.
