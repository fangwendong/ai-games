# Agents.md

This file is the maintenance note for future Codex-style agents working on `ibkr-bot`.

## Project Shape

- `src/ibkr_bot/` contains the runtime code.
- `tests/` contains unit tests for strategy, risk, and CLI helpers.
- `deploy/headless/` contains the Linux-only headless IB Gateway deployment notes and startup scripts.

## Operating Rules

- Keep changes paper-first and dry-run by default.
- Do not enable live trading unless the user explicitly asks and the risk controls are already in place.
- Preserve `run-once` as a compatibility alias when changing the CLI.
- Keep user-visible updates going through `botmux send`; terminal output is not visible to the user.
- Prefer small, local edits over broad refactors.

## Common Commands

Run these from `ibkr-bot/`:

```bash
python3 -m ruff check src tests
python3 -m pytest -q
ibkr-bot init-db
ibkr-bot check-connection
ibkr-bot quote --symbol SPY
ibkr-bot scan
ibkr-bot scan --strategy quality_low_vol_rotation
ibkr-bot scan --strategy five_minute_momentum --duration '2 D' --bar-size '5 mins'
ibkr-bot rebalance
ibkr-bot backtest --duration '3 Y'
ibkr-bot backtest --duration '3 Y' --profile daily
ibkr-bot backtest --strategy short_term_momentum_rotation --duration '1 Y'
ibkr-bot backtest --duration '3 Y' --rebalance-frequency daily --lookback 20 --volatility-window 10 --volume-window 10
ibkr-bot trade-once --symbol SPY
```

## Maintenance Checklist

When changing trading behavior, update these together:

1. CLI entry points in `src/ibkr_bot/main.py`
2. Broker adapters in `src/ibkr_bot/broker/`
3. Model types in `src/ibkr_bot/models.py`
4. Risk checks in `src/ibkr_bot/risk.py`
5. Tests in `tests/`
6. User docs in `README.md` and `docs/`

## Deployment Notes

- The documented headless deployment is Linux on Debian-class systems.
- Gateway and IBC are expected to live under `/home/fwd/ibkr` in the current setup.
- The bot connects to `127.0.0.1:4002` for paper trading unless configuration says otherwise.
- The rotation path uses an automatic liquid ETF catalog by default; `IBKR_ROTATION_SYMBOLS` is only for overrides.
- `ibkr-bot backtest` defaults to the monthly profile, but can be switched to the daily profile for faster-cycle experiments. Explicit windows override the profile defaults.
- `short_term_momentum_rotation` is the daily rotation option and defaults to a 30-bar lookback.
- `five_minute_momentum` is the intraday scan path and defaults to 5-minute bars over 2 trading days.

## Things To Keep Stable

- `IBKR_DRY_RUN` should default to `true`.
- `IBKR_ALLOW_LIVE` should default to `false`.
- `IBKR_ALLOW_EXTENDED_HOURS` should default to `false`.
- `ALERT_COMMAND` should remain botmux-compatible.
- SQLite audit logging should stay on by default.
