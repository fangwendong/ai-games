# Server, botmux, And IBKR Health Monitor

This runbook documents the five-minute health monitor for this host. It is an
operations check, not a trading strategy and not a market-data validator.

Do not include account IDs, balances, positions, orders, credentials, quote
prices, bar contents, or raw cache payloads in health reports.

## Scope

The monitor reports on four areas:

1. Physical resources: CPU, load, memory, swap, root/data-disk usage, and the
   highest CPU/memory processes.
2. botmux: active/recoverable sessions, safe zombie cleanup, scheduled-task
   counts, and current-session protection state.
3. IBKR infrastructure: Gateway/IBC processes, API port `4001`, and a forced
   read-only server-time heartbeat.
4. Runtime infrastructure: process/tmux presence and file activity for the
   quote cache, live context cache, and deterministic live strategy reporter.

The monitor must not inspect SMART/ARCA values, symbols, prices, bars, cache
latency, or price scale. Cache checks use process state and `stat` only.

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

The heartbeat must load the live checkout `.env` and then override it with:

```text
IBKR_READONLY=true
IBKR_DRY_RUN=true
IBKR_ALLOW_LIVE_TRADING=false
IBKR_CLIENT_ID=87
```

It may run only `python -m ibkr_quant_bot.cli heartbeat`. It must not run a
strategy, read account state, or submit/modify/cancel orders.

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
- the legacy Codex polling schedule is unexpectedly resumed.
- collection or permitted cleanup fails.

A one-sample CPU increase below the threshold is informational. Task-count
changes alone are not an alert; validate named current-stage protection instead.

## Trading-Stage Protection

The deterministic runner replaces the old one-minute Codex schedule. Its
supervisor is `ibkr-live-strategy-reporter` and remains alive across sessions.
It executes at seconds `03/13/23/33/43/53`, sends chat only at `:03`, and gates
execution to 09:30-16:00 America/New_York on weekdays. The broker calendar
remains authoritative for holidays and early closes.
The reporter loop exits itself at normal close as a fallback if an external
stop task is delivered but not acted on.

- The legacy `af15c80b` Codex polling task must remain paused.
- Exactly one `ibkr-live-strategy-reporter` tmux session and one
  `run-live-strategy-report-loop.zsh` process must exist.
- During the regular session, `latest-summary.txt` and `latest-run.log` must be
  no more than 120 seconds old and `latest-run.log` must contain
  `runner_exit=0`.
- Outside the regular session, summary freshness is not required.
- Old one-time start/stop tasks may exist, expire, or be removed without an
  alert because they no longer control the deterministic reporter.

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

Then include `核心概览` with resource, botmux, IB, and cache/reporter status. End with
`指标明细`, expanding:

- CPU/idle and load 1/5/15;
- used/available memory and swap;
- root and `/home` disk usage;
- highest CPU and memory processes;
- active sessions, cleanup count, enabled/paused task counts, and trading stage;
- Gateway/IBC/port/heartbeat state; and
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
