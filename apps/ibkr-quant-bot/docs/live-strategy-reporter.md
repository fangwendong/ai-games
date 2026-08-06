# Deterministic Live Strategy Runner And Reporter

The live runner removes the language model from the execution path. A
persistent supervisor runs the explicit `rotation-hysteresis-v5` command every
ten seconds, parses
its structured JSON blocks, and keeps the latest fixed Chinese summary. The
first completed execution in each ET minute sends that summary directly
through `botmux send`, so chat reports remain once per minute.

## Runtime files

- One-shot runner: `scripts/run-live-strategy-report.zsh`
- Persistent supervisor: `scripts/run-live-strategy-report-loop.zsh`
- Daily start wrapper: `scripts/start-live-strategy-reporter.zsh`
- Daily close wrapper: `scripts/close-live-strategy-reporter.zsh`
- Daily stop wrapper: `scripts/stop-live-strategy-reporter.zsh`
- Formatter: `src/ibkr_quant_bot/live_report.py`
- Latest sanitized summary: `.ibkr_bot_state/live-strategy-reporter/latest-summary.txt`
- Latest runner status: `.ibkr_bot_state/live-strategy-reporter/latest-run.log`

Only the latest summary and runner status are retained. Raw strategy output is
kept in a temporary directory and deleted after each run, so logs cannot grow
without bound and account/order representations are not persisted.

## Required environment

The supervisor inherits the live checkout's `.env` and requires these
additional non-secret variables:

```text
BOTMUX_REPORT_SESSION_ID=<botmux sender session used by the reporter>
BOTMUX_REPORT_ROOT_MESSAGE_ID=<target Feishu topic root message ID>
```

The two values are one routing tuple and must not be updated independently.
`BOTMUX_REPORT_SESSION_ID` pins the botmux sender context. The start wrapper
copies it to `BOTMUX_SESSION_ID` inside the tmux supervisor so later sends do
not inherit the session that happened to launch the wrapper.

`BOTMUX_REPORT_ROOT_MESSAGE_ID` must be the topic/thread root message's
`messageId`, not a reply message id and not the nested `rootId` field from a
child reply. When a report is routed to the wrong place, inspect
`botmux history --scope chat` using the configured report session and use the
root message's own `messageId` as the router target. Using a normal reply
message id will create a dead-end thread target or fail to land where the
operator expects. The start wrapper also keeps the current root id in
`.ibkr_bot_state/live-strategy-reporter/root-message-id.txt` so a later auto
start can recover the same thread without manual re-entry.

Before starting the reporter, verify three things:

1. `BOTMUX_REPORT_SESSION_ID` is the validated sender session and
   `BOTMUX_REPORT_ROOT_MESSAGE_ID` points at the intended topic root.
2. The quote cache and context cache are healthy, and the context cache
   already contains at least one completed 5-minute bar for `QQQ`, `SOXL`,
   and `SOXS`.
3. The next execution lands inside the regular 09:30-15:59
   America/New_York window.

If any of those checks fail, delay the reporter instead of starting it early.
Starting too early can produce fail-closed summaries before the first complete
bar is available, and those summaries should not be treated as a valid daily
report.

The runner always forces live market data and disables ARCA fallback. It does
not override the live/readonly/dry-run/allow-live-trading switches from `.env`.
It runs only from 09:30 through 15:59 America/New_York on weekdays. The broker
calendar remains authoritative; a holiday or early-close result is suppressed.
The supervisor runs at seconds `03/13/23/33/43/53` of each minute. The first
completed execution observed in each ET minute sends a chat report. Other slots
execute the strategy but only update the bounded local latest-summary/latest-
run files. Runs are strictly serial: a slow execution skips a later wall-clock
slot instead of overlapping another strategy process.

The supervisor also exits itself at or after `16:00 America/New_York` on a
weekday, or immediately on a weekend. This is a deterministic fallback for a
missed external stop task. It closes only the strategy supervisor; quote and
context caches, Gateway, heartbeat, and health monitoring remain independent.

## Safe validation

Generate a report without submitting orders or sending a message:

```bash
BOTMUX_REPORT_SAFE_TEST=true \
BOTMUX_REPORT_DRY_SEND=true \
BOTMUX_REPORT_FORCE_RUN=true \
scripts/run-live-strategy-report.zsh
```

## Start and stop

Use the dedicated wrappers for a daily open/close schedule. The start wrapper
is idempotent and only launches the supervisor when the tmux session is not
already running. The stop wrapper is also idempotent and is safe to run after
the loop has already exited itself at the close.

```bash
BOTMUX_REPORT_SESSION_ID=<botmux session ID for target chat> \
BOTMUX_REPORT_ROOT_MESSAGE_ID=<topic root message ID> \
scripts/start-live-strategy-reporter.zsh

scripts/close-live-strategy-reporter.zsh

scripts/stop-live-strategy-reporter.zsh
```

Never run this supervisor together with the old one-minute Codex schedule. The
CLI runtime lock prevents simultaneous execution, but duplicate schedulers
would still create skipped runs and duplicate status messages.

Recommended botmux schedule pair:

- start the reporter on weekdays shortly after the market opens, using
  `scripts/start-live-strategy-reporter.zsh`;
- stop the reporter on weekdays after the close, using
  `scripts/close-live-strategy-reporter.zsh` so the daily review log is
  appended before shutdown.

Set both `BOTMUX_REPORT_SESSION_ID` and `BOTMUX_REPORT_ROOT_MESSAGE_ID` before
starting the wrapper. The session pins the botmux sender context and the root
message selects the topic. Supplying only a new root while retaining an
unvalidated session can send reports to the wrong place or make the topic
appear silent.

The root message id must be the topic root message's `messageId`. Do not use
the `rootId` field from a reply, and do not point at a child message.

The loop still self-exits at or after the close. The explicit stop task is the
fallback that keeps the tmux session from lingering when a prior command fails
to act. The close wrapper is the preferred daily close path because it appends
the sanitized review log first and then shuts the reporter down.

## Failure Modes To Avoid

- If a report does not appear in the expected topic, verify the session/root
  routing tuple in both `.env` and the running tmux process environment.
- If the reporter is running but the first few runs fail closed, check whether
  the context cache was started before the first completed 5-minute bar.
- If the health monitor says the reporter is missing while the tmux session
  and loop process are both alive, treat that as a monitor-logic issue until
  the runbook checks are reconciled.

## Topic Routing Gotcha

When starting the reporter for a new conversation, create the target chat and
topic first. Do not reuse a visible reply message id from inside the thread,
and do not use the child reply's `rootId` field as the destination. The
correct flow is:

1. create or identify the target chat and topic root message;
2. configure the botmux session for that chat as
   `BOTMUX_REPORT_SESSION_ID`;
3. copy the topic root's `messageId` as
   `BOTMUX_REPORT_ROOT_MESSAGE_ID`;
4. restart the reporter loop; and
5. verify the next automatic summary arrives under that same thread.

## Current Production Destination

The live deployment is intentionally isolated from the operator's general
group:

- Feishu chat: `IBKR 实盘策略报告`
- chat id: `oc_b6300eaeaeff7062ae60ff10a943a197`
- botmux report session:
  `b50a1dea-b972-4c98-8f90-d04f8fb464aa`
- report topic root:
  `om_x100b69b963a3bca0def99403d4d4d30`

These identifiers are operational routing metadata, not secrets. Keep their
active values in the ignored live `.env`; the checked-in values above are the
recovery record. When moving the reporter again, update the session and root
together, restart the supervisor, verify its process environment, and confirm
an automatic report in the destination before declaring the move complete.

## Manual-order isolation

Never leave V5 automation in control while an operator is manually trading
SOXL or SOXS. The generic live `order` command writes the manual pause marker
before submitting the broker order. Each strategy run independently checks the
same marker and also detects active non-strategy orders or positions that lack
a strategy-owned entry record. Either symbol pauses the entire coupled
SOXL/SOXS rotation.

While the marker is active, the strategy must not place entries, exits,
protective orders, or mandatory end-of-day flatten orders. The report shows an
amber manual-takeover state. The marker is persistent and must be cleared only
after an operator verifies that the manual position and every related order are
resolved:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli strategy-control status
PYTHONPATH=src python -m ibkr_quant_bot.cli strategy-control resume SOXS
```

Do not resume automation merely because the account is currently flat. A
manual order may still be active or may receive a late fill.

## Summary contract

Every normal report is generated by code and includes, in this order:

1. the final execution conclusion and whether another order is possible;
2. color-marked SOXL/SOXS trade, position, signal, and reason blocks;
3. usable cash, reserve, duration, ET/CST completion time, and QQQ benchmark;
4. stop/take values and broker-hosted protection state when a position exists;
5. SMART bar/quote source, quote age, bar counts, exit code, and exception state.

If the strategy command fails, the reporter sends a fail-closed message but
does not include raw exception text that could expose account or order details.
