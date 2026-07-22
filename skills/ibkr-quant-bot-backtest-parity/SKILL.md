# IBKR Quant Bot Backtest Fill Parity

Use this skill when working on `apps/ibkr-quant-bot` backtests, fill
comparisons, historical cache maintenance, or live-vs-backtest alignment.

## Hard rules

- Keep the signal layer on `5 mins`.
- Use `30 secs` as the default fill layer for current `rotation-hysteresis-v2`
  comparisons.
- Use `1 min` fill only for diagnostics, compatibility checks, or sensitivity
  analysis.
- Do not mix fill bar sizes in the same comparison run.
- Do not mix SMART and ARCA bars in the same cache directory.
- Keep signal cache and fill cache in separate roots.
- Do not treat `QQQ` 1-minute history as required for v2 signal logic; it is
  only useful when studying fill-resolution effects.

## Canonical cache roots

- `SMART 5m`: `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth`
- `SMART 1m`: `/home/fwd/data/ibkr-quant-bot/historical/1-min-rth`
- `SMART 30s`: `/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth`
- `ARCA 5m`: `/home/fwd/data/ibkr-quant-bot/historical/5-min-rth-arca`

## Required workflow

1. Refresh the signal cache first, then the fill cache if needed.
2. Run `history_audit` on the exact cache root and bar size before backtesting.
3. For live-aligned comparisons, keep the signal backtest on `5 mins` and set
   `--fill-bar-size "30 secs"` unless you are explicitly comparing fill
   sensitivity.
4. Record the strategy profile, signal bar size, fill bar size, cache roots,
   capital, notional cap, risk cap, commission, slippage, and spread in the
   report.
5. When comparing results, state whether the difference comes from signal
   logic or from fill resolution.

## Recommended commands

Refresh signal history:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "3 Y" \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

Refresh default fill history:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "3 Y" \
  --bar-size "30 secs" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth
```

Backtest with the live-aligned default fill proxy:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --duration "930 D" \
  --bar-size "5 mins" \
  --fill-bar-size "30 secs" \
  --fill-data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth \
  --reuse-data \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --capital 4500 \
  --max-notional 10000 \
  --commission-per-order 1 \
  --slippage-bps 1 \
  --spread-bps 1
```

Backtest a fill-resolution sensitivity check:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --duration "930 D" \
  --bar-size "5 mins" \
  --fill-bar-size "1 min" \
  --fill-data-dir /home/fwd/data/ibkr-quant-bot/historical/1-min-rth \
  --reuse-data \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

## Reporting standard

When presenting a result, include:

- signal bar size
- fill bar size
- data roots used for signal and fill
- first / last trading session
- `capital`, `max_notional`, `max_risk_per_trade`
- commission, slippage, spread
- net return, trade count, win / loss count
- whether the result is a live-aligned baseline or a diagnostic variant

