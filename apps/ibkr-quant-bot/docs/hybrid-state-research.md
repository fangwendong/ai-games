# GapGuard Fusion v1 Research

`GapGuard Fusion v1` (`gapguard-fusion-v1-research`) is the frozen name for
this research candidate. "GapGuard" identifies the extreme gap-down risk and
recovery filter, while "Fusion" identifies the causal combination with the
unchanged `rotation-hysteresis-v2` baseline. The name is research-only and does
not identify a live profile.

This experiment keeps `rotation-hysteresis-v2` completely frozen and evaluates
v2 and the gap-reversion candidate in timestamp order. The first executable
fill wins the session; v2 wins an exact-time tie. The two strategies never hold
simultaneous positions, and both share one cash balance, USD 4,000 notional
cap, USD 120 risk budget, and the same transaction-cost model.

The evaluator is research-only:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.hybrid_state_research \
  --gap-config config/gap-reversion-v1-research.json \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

The causal replay never asks whether v2 will trade later in the day. If gap
fills first, any later v2 signal is suppressed by the one-entry-per-day rule.
If v2 fills first, gap is suppressed. The shared-cash replay conservatively
retains the v2 backtest share count and reduces it if the hybrid cash balance
cannot fund that count.

## Exploratory Result

| Period | Frozen v2 | GapGuard Fusion v1 | Delta | Gap fallback trades |
|---|---:|---:|---:|---:|
| 2025-07-17 to 2025-10-14 | +3.00% | +13.15% | +10.16 pp | 9 |
| 2025-10-15 to 2026-01-14 | +11.35% | +12.52% | +1.18 pp | 6 |
| 2026-04-14 to 2026-07-14 | +30.83% | +35.03% | +4.20 pp | 8 |
| 2024-07-15 to 2026-07-14 | +60.19% | +73.43% | +13.25 pp | 43 |

The first implementation incorrectly admitted a gap trade only after knowing
that v2 had no trade anywhere in the session. That non-causal result is
withdrawn. The table above uses entry timestamps and contains no same-session
lookahead.

The numerical target is reached on the inspected history, but the evidence is
not independently validated. The 4% minimum gap and maximum opening RVOL of 4
were added after diagnosing the full history. Across eight consecutive
approximately 63-session blocks, the hybrid beats v2 in five, is effectively
flat in one, and trails in two. The two losing blocks prevent a live promotion
despite the higher aggregate return.

Freeze these rules and collect a new forward paper period. Do not change the
live v2 profile, scheduler, or order path. A promotion decision requires the
hybrid to retain a positive after-cost delta over v2 on new data and not worsen
drawdown or operational risk.
