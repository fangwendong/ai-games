# Live Strategy Review Log

This is the sanitized, append-only review log for the semiconductor rotation
strategy. It records live strategy behavior and later replay evidence without
committing account identifiers, broker order IDs, execution IDs, balances, or
unrelated holdings.

All times are America/New_York unless stated otherwise. Dollar PnL is rounded
to cents. "Net PnL" means broker-reported realized PnL after reported
commissions for the strategy round trip; it is not account-wide PnL.
"Net return" is net PnL divided by the actual filled entry notional. This
trade-level denominator is reproducible without exposing account equity and
does not assume that unused account cash was strategy capital. A session with
no entry has no entry-notional denominator and is reported as `N/A`.

## Evidence Hierarchy

Use the following sources in order when adding a session:

1. IBKR executions and commission reports from the ignored live runtime state.
2. The strategy entry and order-state journals under
   `.ibkr_bot_state/semiconductor_rotation_intraday/`.
3. A fixed-profile historical replay using the same session bar source as
   live signal generation.
4. Operator chat or screenshots only as supplementary evidence.

Do not copy raw runtime records into Git. They can contain account numbers,
broker IDs, OCA group names, and other private metadata. Record only the
sanitized fields used below.

## Daily Close Automation

The post-close maintenance command is
`PYTHONPATH=src python -m ibkr_quant_bot.cli append-live-review-log`.
It reads the current session's sanitized journals under
`.ibkr_bot_state/semiconductor_rotation_intraday/` and appends a single
session block to this document if the date is not already present. If the day
has no filled entry yet, the command records a no-trade snapshot instead of
inventing a result.

Run it after the regular US close, once the exit and commission records have
settled. The scheduled task should stay separate from the live 10-second
strategy runner, quote cache, and context cache.

## Session Summary

| Session | Profile | Bar / execution source | Result | Exit | Net PnL | Net return |
|---|---|---|---|---|---:|---:|
| 2026-07-10 | V1-compatible | SMART / SMART | SOXL round trip | Software exit | +$1.43 | +0.38% |
| 2026-07-13 | V1-compatible | SMART / SMART | SOXS round trip | Mandatory 15:50 flatten | +$23.61 | +0.59% |
| 2026-07-14 | `rotation-hysteresis-v2` | SMART / none | No entry | No signal before cutoff | $0.00 | N/A |
| 2026-07-15 | `rotation-hysteresis-v2` | ARCA / SMART | SOXS round trip | Protective take | +$146.30 | +3.70% |
| 2026-07-16 | `rotation-hysteresis-v2` | SMART / SMART | SOXS round trip | Protective take | +$145.93 | +3.69% |

Across these five sessions, the strategy closed four attributable round
trips for approximately $317.27 net realized PnL, or +2.59% of the four
filled entry notionals pooled together. This pooled rate is descriptive and
is not an account return or a compounded portfolio return. All four trades
were profitable, but four trades are far too few to estimate a reliable win
rate or expected return.

The July 10 and July 13 entry journals predate persistence of an explicit
`strategy_version` field. The repository deployment timeline identifies them
as V1-compatible behavior, but the log does not claim a more precise version
than the stored evidence supports.

## 2026-07-10

### Execution

- Entry: bought 2 SOXL at 12:00:30, average price $189.56.
- Protective orders were created after the entry. The take limit was $196.67.
- Exit: sold all 2 SOXL at 14:46:11, average price $191.28.
- Gross PnL: $3.44.
- Reported round-trip commissions: approximately $2.01.
- Broker-reported net realized PnL: approximately $1.43.
- End state: the recorded SOXL strategy position was flat.

### Review

The entry journal and execution records prove the fill and exit, but the
software-exit decision reason was not persisted in the older order journal.
The review must therefore label it only as a software exit rather than infer a
technical or benchmark reversal after the fact.

The unusually small two-share size reflects the order that actually passed
the live sizing and broker checks. Do not replace it with a theoretical
$4,000 position in an execution review.

## 2026-07-13

### Execution

- Entry: bought 873 SOXS at 12:05:11, average price $4.565 before the later
  1:10 reverse split.
- Protective take: $4.74; it was not reached.
- Exit: the mandatory pre-close path cancelled the protective OCA and sold all
  873 shares at 15:50:13 in two fills, average price $4.602344.
- Gross PnL: approximately $32.60.
- Reported round-trip commissions: approximately $8.99.
- Broker-reported net realized PnL: approximately $23.61.
- End state: the recorded SOXS strategy position was flat.

### Review

This session verifies that the ten-minute-before-close flatten path operated
as designed when neither protective order closed the position earlier. The
high share count and sub-$5 prices are the valid pre-reverse-split scale and
must not be compared directly with post-split July 15 prices.

## 2026-07-14

### Execution

- No entry journal and no strategy order journal were created.
- A same-parameter replay used 78 complete regular-session 5-minute bars for
  each of QQQ, SOXL, and SOXS.
- Result: zero trades, zero commission, and zero PnL.

### Why No Order Was Correct

- Before 11:55, fewer than 30 completed bars were available, so the strategy
  was still warming up.
- From 11:55 through 12:30, QQQ was bearish and only SOXS was eligible. SOXS
  did not simultaneously satisfy its EMA trend-gap and two-bar VWAP
  confirmation requirements.
- After 12:35, QQQ became bullish and only SOXL was eligible. Its trend gap
  remained just below the long threshold through the final eligible signal.
- The first complete raw SOXL entry signal arrived at 13:45, after V2's 13:30
  new-entry cutoff, and was correctly rejected.

A counterfactual replay that removed only the cutoff would have entered SOXL
at about 13:50 and lost approximately $26.29 net. This counterfactual is a
diagnostic, not a reason to retune the frozen cutoff.

### Review

The live polling continued through the session and the live and development
strategy files matched at review time. This was an intentional no-trade
session, not a polling failure or missing-bar failure.

## 2026-07-15

### Market-Data Context

SOXS began trading on a post-1:10-reverse-split scale. IBKR SMART real-time
quotes were available, but SMART historical bars for SOXS were not. The
guarded fallback pinned all three signal series (QQQ, SOXL, and SOXS) to ARCA
for the entire session. Live quotes and orders remained SMART. No session or
symbol mixed SMART and ARCA bars.

### Execution

- Entry: bought 83 SOXS at 12:00:18 in two SMART-routed fills, average price
  $47.611981.
- Entry limit: $47.75.
- Protective take: $49.40 for all 83 shares.
- Protective stop: approximately $46.43 for all 83 shares.
- At 12:19, the position was above the 3% profit-lock activation threshold,
  but the latest completed close had not fallen 0.6% from its peak. The
  strategy correctly continued holding.
- Exit: the $49.40 protective take filled all 83 shares at 12:24:24; the OCA
  stop was cancelled automatically.
- Gross PnL: approximately $148.41.
- Total reported transaction costs implied by the final realized result:
  approximately $2.11.
- Broker-reported net realized PnL: approximately $146.30.
- End state: SOXS was flat with no remaining strategy protective order.

The one-entry-per-session guard prevented a second entry after the take-profit
exit. This is deliberate: earlier backtests found that looser same-day
re-entry worsened results.

### Backtest Reconciliation

The old close-only backtest produced $110.50 and incorrectly labeled the exit
as `profit_lock`. The corrected protective-OCA model produced $146.19 and
`protective_take`, only about $0.11 below the broker result.

The corrected model uses bar high/low only to determine whether a protective
order was touched:

- a sell take limit fills at its limit, or at a better opening price after an
  upward gap;
- a sell stop fills at its stop, or at a worse opening price after a downward
  gap; and
- if both levels occur in one bar and their order is unknowable, the stop is
  assumed first.

It does not use the bar high as the take fill or the bar low as the stop fill.
The July 15 one-minute replay narrowed the take event to 12:24, matching the
live minute. Remaining price error came mainly from SMART/DARK entry price
improvement that ARCA OHLC bars cannot reconstruct.

The execution-model fix is commit `a166ec6` on `wt/codex-6`. A 60-session
check changed net return from 30.38% to 30.15% while preserving 55 trades and
the same 27/28 win-loss count, which supports treating it as an execution
semantics correction rather than a one-day parameter fit.

## 2026-07-16

### Market-Data Context

QQQ, SOXL, and SOXS signal bars used SMART for the complete session. Live
quotes and order routing also used SMART. The standalone quote subscription
was active, while the strategy retained its fail-closed SMART snapshot path
for stale-cache handling. No ARCA fallback or mixed signal source occurred.

### Execution

- The 30-bar warm-up completed at 12:00. QQQ was bearish, SOXL was rejected,
  and SOXS passed its EMA, trend, VWAP, score, and benchmark-regime filters.
- Entry: bought 77 SOXS at 12:01:46 in two SMART-routed fills, weighted average
  price $51.387477. The entry limit was $51.40.
- Protective stop: $50.23 for all 77 shares.
- Protective take: $53.31 for all 77 shares.
- While held, SOXS retained a bullish fast/slow/trend EMA structure and QQQ
  remained in the bearish regime. No technical, benchmark, or profit-lock
  software exit occurred before the protective take.
- Exit: the $53.31 protective take filled all 77 shares at 13:45:45. The OCA
  stop was cancelled and no strategy order remained active.
- Gross PnL from sanitized fills: approximately $148.03.
- Broker USD realized PnL after the round trip: $145.93, implying approximately
  $2.10 of total transaction costs.
- Net return on the $3,956.84 filled entry notional: approximately +3.69%.
- End state: SOXS and SOXL were flat, with no active strategy order.

The broker execution query returned only this SOXS strategy round trip for the
session. The recorded USD realized PnL therefore reconciles to the trade after
the approximately $2.10 difference between gross fill PnL and realized PnL.
No account identifier, order identifier, execution identifier, balance, or
unrelated holding is retained in this log.

### Review

This session exercised the intended V2 path: wait for 30 completed bars, select
the inverse semiconductor ETF only under a bearish QQQ regime, create complete
broker-hosted OCA protection after the fill, and allow the protective take to
close the position without waiting for the next polling cycle. The entry was
filled before the 13:30 cutoff; after the 13:45 exit, the one-entry-per-session
guard continued to prevent re-entry.

A same-source historical replay has not yet been appended for this session.
When added, it must use the complete 2026-07-16 SMART bar set and the corrected
protective-OCA execution model; it must not substitute ARCA bars or infer the
two live entry fills from a favorable bar extreme.

## 2026-07-17

### Market-Data Context

- Bar / quote / order route: SMART / SMART / SMART
- Source decision: all strategy symbols passed SMART validation

### Execution

- Session date and profile: 2026-07-17 / rotation-hysteresis-v2
- Bar source / quote source / order route: SMART / SMART / SMART
- Data completeness and corporate actions: entry journal recorded; no
  corporate-action event is reflected in the session snapshot
- Signals considered and rejected: SOXL entry signal was accepted; SOXS stayed
  out of the bullish regime
- Entry time, symbol, quantity, average fill, and reason: 12:00:04 ET, SOXL,
  21, $138.88, entry signal satisfied
- Protective stop/take created: stop $133.35 / take $144.09
- Exit time, quantity, average fill, and reason: N/A; no exit fill found in
  the current journal snapshot
- Gross PnL, commissions, broker net realized PnL, and net return on entry
  notional: N/A until an exit fill is recorded
- End-of-session position and open-order state: entry recorded; protective OCA
  orders remain active in the stored journal snapshot

### Review

The stored evidence confirms the entry and the protective orders, but the
closeout leg is not present in the current journal snapshot yet. Reconcile the
exit before treating this day as a completed round trip.

## Follow-Up Items

- Persist the exact strategy version on every entry. This is already present
  in the July 15 journal but absent from the earlier journals.
- Persist the software exit reason alongside the order record, not only a
  generic `-exit` reference.
- Reconcile broker-side protective fills into the local order journal even
  when the fill occurs between polling runs.
- Archive timestamped SMART quote snapshots around order submission so future
  replays can distinguish signal error from routing and price improvement.
- Keep recording no-trade sessions and data-source selection; otherwise the
  review sample will be biased toward days with fills.

## Append Template

For each completed session, add:

```text
Session date and profile:
Bar source / quote source / order route:
Data completeness and corporate actions:
Signals considered and rejected:
Entry time, symbol, quantity, average fill, and reason:
Protective stop/take created:
Exit time, quantity, average fill, and reason:
Gross PnL, commissions, broker net realized PnL, and net return on entry notional:
End-of-session position and open-order state:
Same-source replay result and live/replay difference:
Operational anomalies and follow-up:
```

Never include account identifiers, broker order or execution IDs, balances,
unrelated positions, raw environment values, or credentials.
