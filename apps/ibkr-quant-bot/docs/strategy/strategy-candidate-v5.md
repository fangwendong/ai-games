# Strategy Candidate V5

`rotation-hysteresis-v5` is an isolated V2-derived candidate. It does not
replace the current default profile or change the live runner.

## Frozen Changes From V2

- Require completed-bar absolute displacement divided by the session high-low
  range to be at least `0.35` before entry.
- Activate the close-based profit lock at `1.5%` above average cost and exit
  after a `0.5%` drawdown from the highest completed close.
- When the traded ETF has risen more than `10%` from the session open at the
  entry decision, multiply the resolved quantity by `0.50`, rounding down.
- Keep the V2 `3.75%` protective take, stop logic, QQQ regime confirmation,
  30 completed-bar minimum, 13:30 ET entry cutoff, and daily-entry limit.

The entry controls use only completed bars available at decision time. They do
not read future highs or lows. The displacement gate rejects directionless
sessions; the return threshold reduces exposure instead of vetoing a strong
trend outright.

## Validation Snapshot

The selection run used SMART 5-minute signal bars, SMART 30-second fill bars,
the `worst-case` entry fill model, 1 USD commission per side, 1 bp slippage,
1 bp spread, `max_risk_per_trade=120`, and a 5,000 USD capital/notional cap.
The newest cache preflight covered 2026-08-03 and 2026-08-04 with 78 signal
bars and 780 fill bars per symbol per session.

| Window | V2 net | V5 net | V2 trades | V5 trades |
|---|---:|---:|---:|---:|
| 2026-07-22 to 2026-08-04 (10 sessions) | -4.08% | +0.38% | 10 | 9 |
| 2026-07-07 to 2026-08-04 (21 sessions) | +10.48% | +8.89% | 20 | 16 |
| 2026-02-03 to 2026-08-04 (126 sessions) | +35.80% | +45.28% | 117 | 90 |

Four fixed-parameter walk-forward OOS slices were positive for V5, with a
mean return of `5.47%`. The final 20-session holdout returned `8.89%`, versus
`8.04%` for V2. These are inspected research results, not proof of a durable
edge. The large sensitivity between five-minute and 30-second fill resolution
requires further one-year and shadow validation before live promotion.

## Usage

Run the candidate explicitly:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v5 \
  --capital 5000 \
  --max-notional 5000 \
  --duration "6 M" \
  --reuse-data \
  --bar-size "5 mins" \
  --fill-bar-size "30 secs" \
  --fill-data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

`profile-default` resolves to `worst-case` for V5 so the published validation
contract cannot silently fall back to a more optimistic fill model.
