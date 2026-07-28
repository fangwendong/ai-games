# Server, botmux, And IBKR Health Monitor

This runbook documents the five-minute health monitor for this host. It is an
operations check, not a trading strategy and not a market-data validator.

Do not include account IDs, orders, credentials, quote prices, bar contents,
or raw cache payloads in health reports. A sanitized IBKR account snapshot is
allowed and should cover balance and tracked positions only.

## Scope

The monitor reports on four areas:

1. IBKR infrastructure: Gateway/IBC processes, API port `4001`, a forced
   read-only server-time heartbeat, and a sanitized account snapshot
   containing balance and tracked positions.
2. botmux: active/recoverable sessions, safe zombie cleanup, scheduled-task
   counts, and current-session protection state.
3. Physical resources: CPU, load, memory in MB, swap, root/data-disk usage,
   and the highest CPU/memory processes.
4. Runtime infrastructure: process/tmux presence and file activity for the
   quote cache, live context cache, and deterministic live strategy reporter.

The monitor must not inspect SMART/ARCA values, prices, bars, cache latency,
or price scale. Cache checks use process state and `stat` only.

## Current Schedule

- Name: `server_botmux_ib_health_monitor`
- Cadence: every five minutes
- Working directory: `/home/fwd/work/ai-games-wt-codex-7`
- Delivery: the dedicated server-health topic

Schedule IDs are runtime state and change when a task is replaced. Discover the
current ID by name instead of copying an old ID:

```bash
botmux schedule list
```

## Safety Boundary

Every IBKR query must load the live checkout `.env` and then override it with:

```text
IBKR_READONLY=true
IBKR_DRY_RUN=true
IBKR_ALLOW_LIVE_TRADING=false
IBKR_CLIENT_ID=87
```

The monitor may run only these IBKR CLI commands:

- `python -m ibkr_quant_bot.cli heartbeat`
- `python -m ibkr_quant_bot.cli balance`
- `python -m ibkr_quant_bot.cli positions`

The latter two are required for the sanitized account snapshot. Raw command
output may be parsed locally, but account IDs must never appear in the health
report. The monitor must not run a strategy, request quotes/bars, or
submit/modify/cancel orders.

Do not infer account values from an earlier report. If either read-only query
fails, report its fields as unavailable rather than copying the last known
balance or converting missing position data to zero.

## Account Value Semantics

Use the following stable meanings:

- `NetLiquidation` is the primary account-equity health value.
- `TotalCashValue` and `AvailableFunds` are liquidity values, not total assets.
- `GrossPositionValue` and the current position rows explain cash converted
  into securities.
- `FullInitMarginReq` is account margin usage. It is not the strategy cash
  reserve.
- `IBKR_ENTRY_CASH_RESERVE_USD` is the strategy cash reserve and must be
  labelled separately.

A cash decline is not an account-loss alert when it is reconciled by a new or
larger position. For example, buying `quantity * average_cost` of SOXL normally
reduces cash by approximately the same amount while leaving account equity
represented by cash plus position value. Compare `NetLiquidation` to an
equivalent `NetLiquidation` baseline; never compare current cash to a former
cash-only baseline and call the difference unexplained.

Position rules are equally strict:

- report the current read-only API result on every run;
- preserve fractional quantities;
- report zero only when the positions query succeeded and returned no row for
  that symbol; and
- report unavailable when collection failed.

Session cleanup is limited to entries explicitly reported as stopped,
process-exited, and unrecoverable. Never delete an active or unknown session.
Never kill a process, restart a service, or change a schedule from inside the
health task. An operator may perform a separately reviewed cleanup outside the
monitor.

## Thresholds

Raise a decision-level alert when any of these is true:

- CPU is at least 60%.
- available memory is below 500 MiB.
- a monitored disk is at least 85% full.
- Gateway/IBC, port `4001`, or the read-only heartbeat fails.
- the quote/context cache process or expected file activity stops.
- during regular trading hours, the deterministic reporter is missing,
  duplicated, older than 120 seconds, or reports a nonzero runner exit.
  Outside regular trading hours, a missing reporter is expected when the
  supervisor has already exited cleanly at the close or on a weekend.
- the legacy Codex polling schedule is unexpectedly resumed.
- collection or permitted cleanup fails.

A one-sample CPU increase below the threshold is informational. Task-count
changes alone are not an alert; validate named current-stage protection instead.

## Trading-Stage Protection

The deterministic runner replaces the old one-minute Codex schedule. Its
supervisor is `ibkr-live-strategy-reporter` and remains alive across sessions.
It executes at seconds `03/13/23/33/43/53`, sends chat on the first completed
execution in each ET minute, and gates execution to 09:30-16:00
America/New_York on weekdays. The broker calendar remains authoritative for
holidays and early closes.
The reporter loop exits itself at normal close as a fallback if an external
stop task is delivered but not acted on. A separate weekday start task should
launch the tmux supervisor after the open, and a separate weekday stop task
should kill it after the close.

- The legacy `af15c80b` Codex polling task must remain paused.
- Exactly one `ibkr-live-strategy-reporter` tmux session and one
  `run-live-strategy-report-loop.zsh` process must exist.
- During the regular session, `latest-summary.txt` and `latest-run.log` must be
  no more than 120 seconds old and `latest-run.log` must contain
  `runner_exit=0`.
- Outside the regular session, summary freshness is not required.
- Outside the regular session, summary freshness is not required and an absent
  reporter tmux/process is not an alert if the final close flush completed.
- Old one-time start/stop tasks may exist, expire, or be removed without an
  alert because they no longer control the deterministic reporter.

When checking the reporter during the regular session, use the runbook
contract instead of a single process-name test:

- `ibkr-live-strategy-reporter` tmux must exist.
- `run-live-strategy-report-loop.zsh` must be alive.
- `latest-run.log` must keep refreshing with `runner_exit=0`.
- a missing chat post is only actionable if the current run reached a real
  `report_due=true` send slot and still failed to deliver to the expected
  topic.

This avoids the two common false positives seen during the July 2026 incident:
starting the reporter before the first completed five-minute bar, and binding
the reporter to an old topic root so the report lands in the wrong thread.

Daily history refresh and the health monitor itself should remain enabled.
One-time task IDs and dates must be updated when the next live session is
created. Do not keep yesterday's completed start/stop tasks in the protection
baseline.

Intentional operator cleanup must be recorded in the task prompt or baseline so
the next run does not report the known change as an external anomaly.

## Report Format

The report is layered and uses stable emoji color markers because arbitrary
font color is not reliable in chat rendering.

If healthy, start with:

```text
🟢 检查通过｜HH:MM CST
```

If unhealthy, put the abnormal information before every normal metric:

```text
🔴 异常：<most important problem>
影响：<current impact>
建议：<next action>
```

Then include `核心概览` with IB account snapshot, botmux, resource, and
cache/reporter status. End with
`指标明细`, expanding:

- NetLiquidation, TotalCashValue, AvailableFunds, GrossPositionValue, current
  tracked positions, account margin usage, and the separately labelled
  strategy cash reserve;
- CPU/idle and load 1/5/15;
- used/available memory and swap, reported in MB;
- root and `/home` disk usage;
- highest CPU and memory processes;
- active sessions, cleanup count, enabled/paused task counts, and trading stage;
- Gateway/IBC/port/heartbeat state; and
- IBKR balance and tracked positions, with account IDs/order IDs omitted; and
- quote/context process counts plus file update time or age; and
- reporter tmux/process counts plus in-session summary age and runner exit.

Do not append the full task list, UTC server timestamp, collection commands,
old-task history, or a duplicate conclusion.

Send the report as a multiline `botmux send` heredoc. Line boundaries must be
real LF characters (`U+000A`), not the two literal characters `\` and `n`.
Before sending, reject and rebuild any body containing a literal `\n`
sequence; passing a JSON-escaped string directly as the message body causes
the chat client to display broken line breaks.

## Safe Task Replacement

botmux currently has no in-place schedule edit. Replace the monitor without a
coverage gap:

1. Read the current task and record its chat, topic, app, cadence, and workdir.
2. Add the replacement task first with the same destination and the revised
   prompt.
3. Confirm the new task is enabled and has a future `next` time.
4. Remove every superseded health-monitor task by ID so only one remains.
5. Run the replacement immediately with `botmux schedule run <new-id>`.
6. Confirm `lastStatus=ok`, review the rendered message, and verify the next run.

For the immediate test, inspect the delivered message itself (for example with
`botmux quoted <message-id>`) and verify that its content contains real newline
characters rather than literal `\n` sequences.

Never leave two five-minute monitors active: duplicate runs waste a botmux
worker and can emit contradictory alerts.

## Post-Change Verification

Check all of the following:

```bash
botmux schedule list
botmux list --plain
tmux list-sessions
```

Expected state:

- exactly one enabled schedule named `server_botmux_ib_health_monitor`;
- no extra health-monitor session created for the same topic;
- a successful immediate test run;
- green output when all thresholds and stage checks pass; and
- red output with the abnormal line first when a controlled check fails.

## Common False Positives

| Symptom | Cause | Correction |
|---|---|---|
| Old stop task disappeared | Prior-day one-time task was intentionally removed | Remove it from the current protection baseline. |
| Task count dropped after cleanup | Count comparison was used instead of named-stage validation | Validate current roles and statuses, not total count. |
| Context file is older than quote file | Context refreshes per five-minute bucket; quotes refresh near one second | Apply service-specific file-age expectations. |
| CPU briefly rises during the check | `mpstat`, botmux, or a scheduled command was active | Alert only at the documented threshold. |
| Completed history worker remains online | Scheduled botmux session did not exit cleanly | Review separately; do not kill it from the health task. |
| Legacy one-minute polling is paused | The deterministic reporter replaced it | Treat paused as the required state; do not resume it. |
| Cash falls after an entry fill | Cash was converted into a security position | Reconcile cash with current positions and GrossPositionValue; judge account equity using NetLiquidation. |
| Positions display zero during a known live holding | Stale state or a failed query was converted to zero | Run the read-only positions query every time; use unavailable on failure. |
| "Reserved amount" is zero while strategy reserve is configured | Account margin and strategy reserve were conflated | Report FullInitMarginReq and IBKR_ENTRY_CASH_RESERVE_USD as separate fields. |
