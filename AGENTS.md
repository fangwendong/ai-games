# AGENTS.md

This file is the first-stop guide for AI agents working in this repository.
Use it to orient quickly, then open the README or runbook for the specific
subproject you are changing.

## Repository Purpose

`ai-games` is a mixed repository for:

- AI-assisted game prototypes under `games/`
- Reusable game-development skills under `skills/`
- A Python IBKR quant trading bot under `apps/ibkr-quant-bot/`
- Small deployment snippets under `deploy/`

Do not assume all folders share one build system. Each subproject has its own
run commands and validation path.

## Top-Level Layout

| Path | Purpose |
|---|---|
| `README.md` | Repository overview and worktree workflow. |
| `AGENTS.md` | This AI orientation guide. |
| `apps/ibkr-quant-bot/` | Interactive Brokers market data, backtest, and live strategy bot. |
| `games/escape-room-doors/` | Static browser escape-room prototype. |
| `games/garden-logic/` | Static browser logic puzzle prototype. |
| `games/night-market-dash/` | Static browser action prototype. |
| `games/night-market-dash-godot/` | Godot 4 version of Night Market Dash. |
| `skills/godot-game-prototyper/` | Reusable Godot prototype skill and agent metadata. |
| `deploy/nginx/` | Nginx snippets for selected static games. |

## General Working Rules

- Prefer a fresh git worktree for independent tasks. The human-facing workflow
  is documented in the root `README.md`.
- Keep edits scoped to the requested subproject. Do not reformat unrelated
  games or bot code.
- Read the local README/design/runbook before changing a subproject.
- For searches, prefer `rg` and `rg --files`.
- Keep generated state, credentials, `.env`, cache files, and local logs out of
  git.
- Default to ASCII in repo files unless an existing file intentionally uses
  another character set.

## Current Important Branch Context

Recent work has focused on `apps/ibkr-quant-bot/`, especially:

- live IBKR market data guards
- semiconductor rotation live strategy
- order-state and daily-entry tracking
- backtest/live exit alignment
- IBKR Gateway and market data runbooks

Before changing live-trading behavior, inspect the latest git history and the
bot runbooks. Trading code has real money implications.

## IBKR Quant Bot

Path: `apps/ibkr-quant-bot/`

Read first:

- `apps/ibkr-quant-bot/README.md`
- `apps/ibkr-quant-bot/docs/ibc-gateway-startup.md`
- `apps/ibkr-quant-bot/docs/ibkr-market-data-troubleshooting.md`

Core modules:

| File | Role |
|---|---|
| `src/ibkr_quant_bot/config.py` | Environment-driven settings. |
| `src/ibkr_quant_bot/broker.py` | IBKR/TWS API boundary via `ib-insync`. |
| `src/ibkr_quant_bot/strategy.py` | Moving-average, VWAP, intraday momentum, and semiconductor rotation strategies. |
| `src/ibkr_quant_bot/backtest.py` | Intraday backtest engine and cost model. |
| `src/ibkr_quant_bot/cli.py` | CLI commands for quotes, account checks, strategies, and backtests. |
| `src/ibkr_quant_bot/risk.py` | Order risk checks. |
| `tests/` | Unit tests for strategy, backtest, live data guards, and risk. |

Common local commands:

```bash
cd apps/ibkr-quant-bot
PYTHONPATH=src python -m pytest tests
PYTHONPATH=src python -m ibkr_quant_bot.cli doctor
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum
```

Safety rules for the bot:

- `IBKR_READONLY=true` and `IBKR_DRY_RUN=true` are the safe defaults.
- Live trading requires both `IBKR_TRADING_MODE=live` and
  `IBKR_ALLOW_LIVE_TRADING=true`.
- Do not silently fall back to delayed market data for live strategy execution.
- The live checkout is separate from the dev/backtest checkout:
  `/home/fwd/work/ai-games-wt-codex-live/apps/ibkr-quant-bot/`.
- Editing the dev checkout does not affect the running live bot unless changes
  are explicitly synced.
- Strategy-specific runtime state belongs under `.ibkr_bot_state/...` and must
  stay ignored by git.

Recent strategy facts worth knowing:

- The current live profile is `rotation-hysteresis`, a semiconductor rotation
  between `SOXL` and `SOXS` with `QQQ` as the regime benchmark.
- The legacy `rotation` profile remains available with `--profile rotation`
  as an explicit rollback path.
- Live strategy uses fresh 5-minute bars and live quote checks.
- Backtest exits are intentionally aligned with live behavior: stop/take exits
  are close-based via `exit_decide()`, not optimistic intrabar high/low fills.
- Daily entry limit has been used as a risk control; tests showed looser
  intraday re-entry significantly worsened recent backtests.
- The real-time market data issue was resolved by ensuring the right IBKR
  subscriptions/API acknowledgement, restarting Gateway through IBC, approving
  2FA, and verifying forced live quotes.

## Static Browser Games

These are plain static web prototypes. They usually run with Python's built-in
HTTP server or by directly opening `index.html`.

### `games/escape-room-doors/`

- Read `README.md` and `design.md`.
- Run:

```bash
cd games/escape-room-doors
python3 -m http.server 4175
```

Open `http://127.0.0.1:4175/`.

### `games/garden-logic/`

- Read `README.md` and `design.md`.
- Run:

```bash
cd games/garden-logic
python3 -m http.server 4174
```

Open `http://127.0.0.1:4174/`.

### `games/night-market-dash/`

- Read `README.md` and `design.md`.
- Run:

```bash
cd games/night-market-dash
python3 -m http.server 4173
```

Open `http://127.0.0.1:4173/`.

Static game validation:

- Open the page in a browser or use Playwright when available.
- Check desktop and mobile-sized viewports.
- Verify no text overlap, blank canvas, broken interaction, or inaccessible
  controls.
- Keep UI changes consistent with the existing prototype style.

## Godot Game

Path: `games/night-market-dash-godot/`

Read first:

- `games/night-market-dash-godot/README.md`
- `games/night-market-dash-godot/design.md`
- `skills/godot-game-prototyper/SKILL.md` when doing substantive Godot work.

Run:

```bash
godot --path games/night-market-dash-godot
```

Headless validation:

```bash
godot --headless --path games/night-market-dash-godot --quit
```

Godot work should preserve a playable loop: objective, controls, challenge,
feedback, win/loss, and fast restart. Do not report a Godot change as done
just because the project launches.

## Skills

Path: `skills/`

The current reusable skill is:

- `skills/godot-game-prototyper/`: guidance for building polished Godot 4 game
  prototypes.

When a project creates a reusable workflow, checklist, Godot pattern, tuning
method, or playtest rubric, extract it into `skills/` instead of leaving it
buried in one game.

## Deployment Snippets

Path: `deploy/nginx/`

This directory contains nginx config snippets for selected static web games.
Treat them as deployment references, not as the source of game behavior.

## Testing And Verification Checklist

Before finishing a task, run the strongest practical checks for the files you
touched:

- IBKR bot: `cd apps/ibkr-quant-bot && PYTHONPATH=src python -m pytest tests`
- IBKR strategy/backtest changes: rerun the relevant `backtest-momentum`
  command and report the parameters used.
- Static games: run the local HTTP server and inspect with a browser or
  Playwright.
- Godot game: run `godot --headless --path games/night-market-dash-godot --quit`.
- Docs only: check links, paths, and that the new doc points to the right
  subproject.

If you cannot run an expected check, say why in the final response.

## Common Pitfalls

- Do not modify the live IBKR checkout by accident when the task is only about
  dev/backtest code.
- Do not commit `.env`, runtime state, order logs, gateway logs, or cache files.
- Do not use delayed IBKR data for live strategy decisions.
- Do not trust recent short-window backtests as proof of robust trading edge.
- Do not add a new framework or build tool to a static game unless the user
  explicitly asks for it.
- Do not leave a game prototype as a launch-only scene with no objective,
  feedback, or restart loop.
