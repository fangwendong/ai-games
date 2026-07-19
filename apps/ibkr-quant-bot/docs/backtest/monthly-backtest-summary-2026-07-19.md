# Monthly Backtest Summary — 2026-07-19

This note captures the live-aligned backtest setup used on 2026-07-19 and the
monthly breakdowns requested for the current `rotation-hysteresis-v2`
configuration.

## Backtest Contract

- Profile: `rotation-hysteresis-v2`
- Signal bar size: `5 mins`
- Fill bar size: `30 secs`
- Entry fill model: `open-pullback`
- Capital: `20000 USD`
- `max_notional`: `20000 USD`
- `max_risk_per_trade`: `800 USD`
- Cost model: `commission_per_order=1`, `slippage_bps=1`, `spread_bps=1`
- Data sources:
  - signal bars: `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`
  - fill bars: `/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`

The cache preflight passed for both bar sizes before each run.

## One-Year Run

Window: `2025-07-18` through `2026-07-17`

| Metric | Value |
|---|---:|
| Initial capital | 20000.00 |
| Gross ending capital | 43893.33 |
| Net ending capital | 42233.46 |
| Gross return | 119.47% |
| Net return | 111.17% |
| Trade count | 209 |
| Wins / losses | 98 / 111 |
| Total commission | 418.00 |
| Total slippage cost | 827.92 |
| Total spread cost | 827.92 |

Monthly net returns for the one-year run:

| Month | Net return | Net PnL | Trades | Win rate |
|---|---:|---:|---:|---:|
| 2025-07 | 1.78% | 355.46 | 7 | 28.57% |
| 2025-08 | 5.14% | 1046.22 | 16 | 43.75% |
| 2025-09 | -4.08% | -873.19 | 14 | 21.43% |
| 2025-10 | 16.46% | 3379.19 | 21 | 47.62% |
| 2025-11 | 11.19% | 2676.03 | 17 | 58.82% |
| 2025-12 | 3.36% | 893.46 | 14 | 42.86% |
| 2026-01 | 5.42% | 1488.26 | 14 | 57.14% |
| 2026-02 | 0.86% | 248.50 | 19 | 36.84% |
| 2026-03 | 6.83% | 1994.64 | 19 | 42.11% |
| 2026-04 | -0.31% | -95.94 | 19 | 47.37% |
| 2026-05 | 4.27% | 1328.66 | 19 | 36.84% |
| 2026-06 | 13.84% | 4490.01 | 19 | 63.16% |
| 2026-07 | 14.36% | 5302.15 | 11 | 81.82% |

## Two-Year Run

Window: `2024-07-18` through `2026-07-17`

| Metric | Value |
|---|---:|
| Initial capital | 20000.00 |
| Gross ending capital | 64070.68 |
| Net ending capital | 60712.34 |
| Gross return | 220.35% |
| Net return | 203.56% |
| Trade count | 430 |
| Wins / losses | 211 / 219 |
| Total commission | 860.00 |
| Total slippage cost | 1665.56 |
| Total spread cost | 1665.56 |

Monthly net returns for the two-year run:

| Month | Net return | Net PnL | Trades | Win rate |
|---|---:|---:|---:|---:|
| 2024-07 | 18.65% | 3730.42 | 8 | 75.00% |
| 2024-08 | 7.24% | 1718.63 | 21 | 52.38% |
| 2024-09 | 2.41% | 613.40 | 17 | 47.06% |
| 2024-10 | 5.36% | 1397.34 | 18 | 55.56% |
| 2024-11 | 4.14% | 1136.84 | 19 | 47.37% |
| 2024-12 | 4.55% | 1302.41 | 18 | 55.56% |
| 2025-01 | 3.83% | 1145.83 | 19 | 47.37% |
| 2025-02 | -1.80% | -559.74 | 17 | 35.29% |
| 2025-03 | 12.39% | 3776.82 | 19 | 47.37% |
| 2025-04 | 5.45% | 1866.48 | 21 | 47.62% |
| 2025-05 | 0.79% | 283.86 | 18 | 55.56% |
| 2025-06 | 4.77% | 1737.72 | 15 | 60.00% |
| 2025-07 | 1.79% | 684.33 | 18 | 44.44% |
| 2025-08 | 2.69% | 1046.22 | 16 | 43.75% |
| 2025-09 | -2.19% | -873.19 | 14 | 21.43% |
| 2025-10 | 8.66% | 3379.19 | 21 | 47.62% |
| 2025-11 | 6.31% | 2676.03 | 17 | 58.82% |
| 2025-12 | 1.98% | 893.46 | 14 | 42.86% |
| 2026-01 | 3.24% | 1488.26 | 14 | 57.14% |
| 2026-02 | 0.52% | 248.50 | 19 | 36.84% |
| 2026-03 | 4.18% | 1994.64 | 19 | 42.11% |
| 2026-04 | -0.19% | -95.94 | 19 | 47.37% |
| 2026-05 | 2.68% | 1328.66 | 19 | 36.84% |
| 2026-06 | 8.82% | 4490.01 | 19 | 63.16% |
| 2026-07 | 9.57% | 5302.15 | 11 | 81.82% |

## Notes

- The strategy stayed on the same signal logic across both runs.
- Only the capital base and `max_notional` were changed for these summaries.
- The fill proxy remained `30 secs` so the backtest stayed aligned with the live execution workflow.
- These are chronological backtests, not OOS / holdout experiments.
