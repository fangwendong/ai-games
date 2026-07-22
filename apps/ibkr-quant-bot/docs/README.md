# IBKR Quant Bot Documentation Index

Start here after reading the repository `AGENTS.md` and the application
`README.md`. This index is the canonical route to every maintained document in
`apps/ibkr-quant-bot/docs/`.

## Live Operations

- [Live Operations index](live/README.md): directory map for operational
  runbooks, caches, and live-session notes.
- [Server, botmux, and IBKR health monitor](live/server-health-monitor.md): scope,
  thresholds, protected tasks, report format, false-positive handling, and the
  safe schedule replacement procedure.
- [IBC Gateway startup](live/ibc-gateway-startup.md): Gateway startup, 2FA, restart,
  watchdog, and local paths.
- [IBKR API heartbeat](live/ibkr-api-heartbeat.md): read-only API heartbeat,
  scheduling, log retention, and failure interpretation.
- [Market-data troubleshooting](live/ibkr-market-data-troubleshooting.md): live
  entitlement, SMART/ARCA behavior, delayed-data guards, and recovery.
- [Live quote cache](live/ibkr-live-quote-cache.md): bounded SMART quote subscription,
  atomic cache, latency fields, singleton process, and recovery.
- [Live context cache](live/ibkr-live-context-cache.md): precomputed trading calendar
  and completed 5-minute bars, validation, fallback, and maintenance.
- [Deterministic live strategy reporter](live-strategy-reporter.md): the
  one-minute reporter supervisor plus its start/stop wrappers, topic-routing
  requirements, and chat-summary contract.
- [Live strategy review log](live/live-strategy-review-log.md): sanitized session
  execution history, reconciliation, net PnL, and review notes.
  When a late broker fill arrives, update the session row and the dated block
  together in the same commit; broker executions are the source of truth.
- [Live strategy audit - 2026-07-17](live/live-strategy-audit-2026-07-17.md):
  prioritized safety findings, fault-injection evidence, repair order, and
  acceptance criteria.

## Historical Data And Backtesting

- [Historical Data And Backtesting index](data/README.md): directory map for
  shared cache and backtest calibration notes.
- [Shared historical market data](data/historical-market-data.md): canonical data-disk
  paths, download, reading, completeness audit, and recent-data refresh.
- [Backtest parameter tuning](backtest/backtest-parameter-tuning.md): frozen parameters,
  transaction costs, chronology, walk-forward checks, and overfitting controls.
- [Live backtest alignment — 2026-07-18](backtest/live-backtest-alignment-2026-07-18.md):
  live-aligned backtest contract, parameter parity, and recent calibration
  conclusions.
- [Monthly backtest summary — 2026-07-19](backtest/monthly-backtest-summary-2026-07-19.md):
  one-year and two-year chronological backtests with monthly net-return tables.
- [Strategy baseline v2](strategy/strategy-baseline-v2.md): current live strategy
  contract, parameters, entry/exit behavior, and operational invariants.
- [Strategy baseline v1](strategy/strategy-baseline-v1.md): frozen rollback baseline and
  comparison reference.

## Isolated Research

- [Strategy index](strategy/README.md): frozen strategy contracts and rollback
  baselines.
- [Research index](research/README.md): isolated experiments and non-default
  candidate notes.
- [Rotation range-gated V1](strategy/strategy-range-gated-v1.md): isolated V2-derived
  candidate that gates new entries on completed-bar QQQ intraday range.
- [Gap reversion research](research/gap-reversion-research.md): isolated gap-down/VWAP
  recovery experiment and live-v2 comparison.
- [Hybrid state research](research/hybrid-state-research.md): GapGuard Fusion causal state
  machine and validation limits.
- [ORB stocks-in-play research](research/orb-stocks-in-play-research.md): isolated opening
  range breakout research and candidate-selection methodology.

## Index Maintenance

When adding, renaming, or removing a Markdown file in this directory:

1. Update this index in the same commit.
2. Keep the root `AGENTS.md` route to this file intact.
3. Update the application `README.md` when the document changes a primary
   operator workflow.
4. Verify every `docs/*.md` file appears in this index and every relative link
   resolves.
