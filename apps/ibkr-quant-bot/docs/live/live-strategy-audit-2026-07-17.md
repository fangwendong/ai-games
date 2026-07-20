# Live Strategy Audit - 2026-07-17

This document records a read-only audit of the deployed
`rotation-hysteresis-v2` execution path. It is a repair backlog, not a change to
the live strategy. No finding in this document authorizes parameter changes or
live deployment by itself.

## Current State At Audit Time

- The one-minute polling task was enabled and completing successfully after
  the completed-bar freshness fix in commit `1871004`.
- QQQ, SOXL, and SOXS used SMART bars and SMART quotes without ARCA fallback.
- Gateway exposed one managed account.
- There were no tracked SOXL/SOXS positions and no tracked non-stock or non-USD
  position rows.
- The full test suite passed: 142 tests and 10 subtests. Compile and Ruff checks
  also passed.

These observations mean none of the latent findings below was actively causing
an unsafe order at audit time. They do not remove the need to fix the uncovered
edge cases.

## Prioritized Findings

### P1: Live Bar Group Is Not Timeline-Aligned

The live loader validates each symbol independently for session date and
freshness, but it does not require QQQ, SOXL, and SOXS to have identical bar
timestamps. Fault injection confirmed that different latest timestamps can
individually pass validation and enter one decision cycle.

A second issue exists in the same path: when the cache file metadata is fresh
but its contained bars fail validation, the loader does not retry the complete
SMART group directly from IBKR. It fails the run even though the documented
fallback contract says invalid cache content should fall through immediately.

Required repair:

1. Require identical, ordered, duplicate-free timelines for all three symbols.
2. Treat any cached-bar content failure as a cache miss.
3. Retry the complete SMART group directly from IBKR exactly once.
4. Fail closed if the direct group is incomplete, stale, delayed, or misaligned.

Acceptance tests must cover one-symbol lag, missing middle bars, duplicate bars,
unsorted bars, cache-content failure with successful direct fallback, and both
cache and direct lookup failing.

### P1: Position And Order Identity Is Too Broad

Tracked positions and several active-order queries primarily identify contracts
by ticker symbol. A synthetic SOXL option row was accepted as a strategy
position. In a multi-account or multi-product Gateway session, another account
or an option sharing the underlying symbol could therefore interfere with
position, reduce-only, or protection logic.

Required repair:

- Resolve the trading account once per run.
- Filter positions, orders, and fills by that account.
- Require `secType=STK`, `currency=USD`, and the qualified contract identity
  used by the strategy.
- Fail closed on ambiguous rows rather than overwriting by symbol.

Acceptance tests must cover multiple accounts, stock plus option positions with
the same symbol, non-USD contracts, and same-symbol orders from another account.

### P1: Protective OCA Is Not Confirmed After Entry

After an entry fill, the bot submits stop and take-profit OCA legs, waits one
second, records state, and returns. It does not prove that both legs are active,
cover the full filled quantity, and share one non-empty OCA group. A rejected
leg or process timeout can leave a temporary protection gap until the next
poll repairs it.

Required repair:

- Confirm both active legs before reporting entry completion.
- Preserve an accepted stop if the take leg fails.
- Retry or raise a decision-level alert when protection cannot be completed.
- Ensure the 60-second watchdog cannot silently turn a filled entry into a
  normal-looking completion without verified broker-hosted protection.

Acceptance tests must cover stop rejection, take rejection, partial entry,
timeout between entry fill and OCA submission, and timeout between OCA legs.

### P2: EMA34 Is Used Before 34 Bars Exist

The profile has `trend_window=34` and `min_bars=30`. The EMA helper clamps its
window to the available bar count, so bars 30 through 33 use changing effective
trend windows. Reports simultaneously hide `trend_ema` until bar 34. Backtest
and live code agree, but the strategy definition is internally inconsistent.

Do not change this directly. First compare the frozen V2 behavior with a
candidate requiring at least 34 completed bars, using identical SMART data,
costs, capital rules, and out-of-sample windows.

### P2: Corrupt Daily Entry State Silently Becomes Zero

A missing entry-state file legitimately means no locally recorded entry. An
existing but malformed file is currently handled the same way. Fault injection
confirmed that corrupt JSON returns an entry count of zero. This can lose the
profit-lock entry time and stored protective prices, and can weaken the daily
entry limit if broker completed-order reconciliation is also unavailable.

Required repair: distinguish missing from corrupt state. Corrupt, malformed,
or schema-invalid state must fail closed and alert.

### Architecture: End-Of-Day Flatten Has No Independent Last Resort

The 15:50 ET flatten branch is correctly evaluated before signal-data loading,
but it depends on the same one-minute botmux polling path. A sustained botmux,
Gateway, or session failure during the last ten minutes can leave a position
overnight. The 16:05 ET stop task pauses polling but does not independently
verify that the account is flat.

Required repair: add an independent, narrowly scoped flatten-protection task
for 15:50-15:59 ET. It should reconcile tracked positions and active sells,
submit only reduce-only exits, verify the result, and alert rather than depend
on signal bars.

## Recommended Repair Order

1. Bar timeline alignment and direct SMART fallback.
2. Post-entry OCA activation confirmation.
3. Account and contract identity isolation.
4. Corrupt state fail-closed handling.
5. Backtest the 34-bar warm-up candidate before any strategy change.
6. Add the independent end-of-day flatten protection task.

## Change-Control Boundary

- Keep `rotation-hysteresis-v2` parameters frozen during safety repairs.
- Do not mix the isolated `rotation-range-gated-v1` candidate into live fixes.
- Run the full test suite and focused failure-injection tests for every repair.
- Sync to the live checkout only after verification and an explicit deployment
  request.
