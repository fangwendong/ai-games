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
4. Market-data infrastructure: process/tmux presence and file activity for the
   quote cache and live context cache.

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
- the current trading-stage task state is wrong.
- collection or permitted cleanup fails.

A one-sample CPU increase below the threshold is informational. Task-count
changes alone are not an alert; validate named current-stage protection instead.

## Trading-Stage Protection

The baseline changes across the session:

- Before the scheduled US open: the polling task is paused; current-day start
  and stop tasks are enabled.
- During the regular session: polling and the stop task are enabled; a
  successfully completed/expired start task is normal.
- After the scheduled stop: polling is paused; a successfully completed/expired
  stop task is normal.

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

Then include `核心概览` with resource, botmux, IB, and cache status. End with
`指标明细`, expanding:

- CPU/idle and load 1/5/15;
- used/available memory and swap;
- root and `/home` disk usage;
- highest CPU and memory processes;
- active sessions, cleanup count, enabled/paused task counts, and trading stage;
- Gateway/IBC/port/heartbeat state; and
- quote/context process counts plus file update time or age.

Do not append the full task list, UTC server timestamp, collection commands,
old-task history, or a duplicate conclusion.

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
