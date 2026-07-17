# Live Strategy Baseline V2

`rotation-hysteresis-v2` is the live profile adopted on 2026-07-14. It keeps
the `rotation-hysteresis-v1` sizing, protective orders, and technical exits,
adds one close-based profit-lock exit, and bounds the daily entry window.

## Change From V1

| Parameter | V1 | V2 |
|---|---:|---:|
| Profit-lock activation | disabled | 3.00% above average cost |
| Allowed close drawdown | disabled | 0.60% from the highest completed 5-minute close |
| Hard take profit | 3.75% | 3.75% |
| New-position cutoff | none | 13:30 America/New_York |

The percentage stop, ATR stop, technical reversal confirmation, benchmark
reversal confirmation, daily entry limit, and mandatory end-of-session flatten
remain unchanged.

Operationally, the mandatory flatten check is evaluated before the normal
three-symbol signal-data load. It needs the IBKR session calendar, position,
and order state, but it does not need fresh QQQ/SOXL/SOXS indicator bars or a
quote-cache sample. This keeps signal-data failure from blocking the final
reduce-only exit attempt.

The live command also holds a strategy-scoped, non-blocking runtime lock shared
by every intraday profile. If a
previous one-shot invocation is still running, the overlap exits without
connecting or evaluating another order. At the start of every accepted run,
the bot cancels any strategy-owned BUY remainder left by a crashed invocation
and confirms the cancellation before continuing. This cleanup also runs in the
mandatory flatten window, including when no position has appeared yet.

Known positions are reconciled before signal market data is loaded. Complete
broker-hosted OCA protection is left untouched. Missing or partial protection
is rebuilt first from the exact stop/take prices persisted after the entry
fill. Legacy state without those fields uses the fixed percentage stop/take as
a conservative fallback. Protection is created before the daily entry state is
recorded, so a state-write failure cannot precede broker-side risk protection.

No new position may fill at or after 13:30 America/New_York. Because decisions
use completed 5-minute bars, the 13:25 bar and all later bars are ineligible to
create an entry. This restriction applies only to new entries. Existing
positions continue through the normal protective, software-exit, and mandatory
end-of-session flatten paths.

## Live Semantics

The profit lock is evaluated only when the ordinary stop, take-profit, and
technical exits have not already fired.

1. Recover the current session's entry time from runtime state.
2. Ignore bars before the entry and ignore the currently forming 5-minute bar.
3. Activate after the highest completed post-entry close reaches 3% above the
   broker-reported average cost.
4. Submit the normal reduce-only software exit after a completed close falls
   0.6% or more below that peak close.

The existing 3.75% protective limit and protective stop remain active. Before
a software profit-lock exit is submitted, the bot uses the same path as other
software exits: cancel protective sell orders, wait for the broker state, run
the reduce-only risk check, and then submit the exit.

If the current session's entry time cannot be recovered safely, the profit
lock fails closed and does not trigger. Existing protective and mandatory
exits continue to operate.

## Evidence And Limitation

In the 2026-05-12 through 2026-07-10 short-window comparison, v2 returned
29.33% net versus 23.70% for v1, with 6.24% versus 7.09% trade-level maximum
drawdown. This is not independent evidence: in the 270-session segmented
check, the profit lock beat v1 in only two of six non-overlapping blocks.

The v2 decision is therefore an explicit live policy choice, not a claim that
the historical improvement is statistically proven. Do not tune the 3% or
0.6% thresholds against the same inspected data. Keep v1 available for
rollback and evaluate v2 on newly accumulated forward sessions.

The entry cutoff was adopted after a separate 270-session actual-cost
comparison. The 13:30 candidate returned 49.35% net with 10.82% trade-level
maximum drawdown, versus 41.91% and 11.74% without the cutoff. It remained
positive in five of six non-overlapping blocks and returned 29.03% under the
double-cost stress model. This is still inspected in-sample evidence, so the
cutoff must remain fixed rather than being tuned to nearby timestamps.

## Version And Rollback

- Current versioned profile: `rotation-hysteresis-v2`
- Rollback profile: `rotation-hysteresis-v1`
- Compatibility alias for the former profile: `rotation-hysteresis` (v1)

Run v2 explicitly:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli intraday-momentum \
  --profile rotation-hysteresis-v2
```
