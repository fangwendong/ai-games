# Monthly Backtest Summary — 2026-07-25

This note captures the current live-aligned `rotation-hysteresis-v2` backtest
run after updating the shared `per_trade_risk` / `max_risk_per_trade` budget
to `120 USD` and lifting the backtest notional cap to the live value.

Note: this historical run used the then-current `open-pullback` fill proxy.
Current backtests now default to `worst-case` for pessimistic comparisons.

## Backtest Contract

- Profile: `rotation-hysteresis-v2`
- Signal bar size: `5 mins`
- Fill bar size: `30 secs`
- Entry fill model: `open-pullback`
- Capital: `10000 USD`
- `max_notional`: `10000 USD`
- `max_risk_per_trade`: `120 USD`
- `exit_confirm_bars`: `3`
- `benchmark_exit_confirm_bars`: `1`
- Cost model: `commission_per_order=1`, `slippage_bps=1`, `spread_bps=1`
- Data sources:
  - signal bars: `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`
  - fill bars: `/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`

## Recent One-Month Run

Window: trailing recent month run from the public historical cache, covering
`2026-06-25` through `2026-07-23`.

| Metric | Value |
|---|---:|
| Initial capital | 10000.00 |
| Gross ending capital | 11285.73 |
| Net ending capital | 11210.97 |
| Gross return | 12.86% |
| Net return | 12.11% |
| Trade count | 21 |
| Wins / losses | 13 / 8 |
| Total commission | 42.00 |
| Total slippage cost | 21.84 |
| Total spread cost | 21.84 |

## Compare With the Earlier 300 Risk Budget

On the same recent-month window, the earlier `300 USD` sizing budget produced
about:

- net return: `17.51%`
- trade count: `19`
- win rate: `57.9%`

The lower `120 USD` budget still keeps cadence similar, but the larger live
notional cap matters a lot. Once the backtest uses the same `max_notional`
as live, the one-month return is materially higher than the earlier
under-sized run.

## Takeaway

- `120 USD` is now the live/backtest default.
- The current one-month run remains profitable after the sizing reduction, and
  the live-aligned notional cap restores most of the earlier return.
- If the goal is to improve absolute PnL without widening risk, the next lever
  should be signal quality rather than raising `per_trade_risk` back up.
