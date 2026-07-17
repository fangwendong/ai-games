# Rotation Range-Gated V1

`rotation-range-gated-v1` is an isolated research candidate. It is not the
live profile and must not replace `rotation-hysteresis-v2` without a separate
promotion decision.

## Rule

The candidate inherits every V2 entry, exit, risk, profit-lock, and 13:30 ET
entry-cutoff parameter. It adds one causal entry gate:

```text
QQQ completed-bar intraday range = max(high) / min(low) - 1
allow a new entry only when range >= 0.75%
```

Only QQQ bars completed by the decision time are used. A blocked signal may be
reconsidered on a later completed bar. The gate applies only to new entries;
it does not delay or suppress stop-loss, take-profit, profit-lock, reversal, or
end-of-session exits.

Run it explicitly:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-range-gated-v1
```

The application default and current live profile remain
`rotation-hysteresis-v2`.

## Research Evidence

The 0.75% threshold was selected on 2025 data, then evaluated without further
tuning on 2026-01-01 through 2026-07-16.

| Window | V2 | Range-gated V1 |
|---|---:|---:|
| 2025 development net return | +10.78% | +17.63% |
| 2025 development trades | 209 | 157 |
| 2025 development max drawdown | 13.92% | 11.88% |
| 2026 holdout net return | about +50.8% | +59.57% |
| 2026 holdout trades | 119 | 112 |
| 2026 Feb-Apr PnL | negative | +$349.28 |

The candidate also retained a positive 2026 result under a doubled-cost stress
test. Threshold sensitivity was not monotonic: 0.65%, 0.85%, and 1.00% were
weaker than 0.75%, while 1.25% lost money in the development sample. This is a
material overfitting warning, so the result is a candidate for forward
observation rather than evidence of a production-ready edge.

For 2026-06-01 through 2026-07-16, both profiles produced the same 29 trades and
the same +39.79% isolated-window return. A larger dollar balance in a continuous
candidate run came from earlier compounding, not different June-July trades.

## Promotion Safety

- Do not change `DEFAULT_MOMENTUM_PROFILE`.
- Do not edit the live checkout or its `.env` during candidate research.
- Compare the candidate and V2 on identical SMART data, costs, capital rules,
  and date boundaries.
- Require forward/out-of-sample evidence before considering promotion.
- Preserve V2 as the explicit rollback profile.
