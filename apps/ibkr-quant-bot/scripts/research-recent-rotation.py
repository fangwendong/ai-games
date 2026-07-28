#!/usr/bin/env python3
"""Compare bounded V2 rotation candidates on fixed chronological windows."""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from statistics import fmean

from ibkr_quant_bot.backtest import (
    BacktestCostModel,
    BacktestResult,
    _filter_days,
    evaluate_fixed_strategy_walk_forward,
    run_intraday_momentum_backtest,
    validate_historical_bar_coverage,
)
from ibkr_quant_bot.cli import ROTATION_HYSTERESIS_V2_PARAMETERS
from ibkr_quant_bot.historical_cache import load_bars, require_market_data_source
from ibkr_quant_bot.strategy import SemiconductorRotationStrategy


SIGNAL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/5-min-rth")
FILL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth")
SYMBOLS = ("SOXL", "SOXS", "QQQ")
DURATION = "930 D"
INITIAL_CAPITAL = 10_000.0
ENTRY_FILL_MODEL = "open-pullback"
COST_MODEL = BacktestCostModel(
    commission_per_order=1.0,
    slippage_bps=1.0,
    spread_bps=1.0,
)


def _session_date(value) -> date:
    return value.date()


def _result_summary(result: BacktestResult) -> dict[str, object]:
    by_symbol: dict[str, dict[str, object]] = {}
    for symbol in ("SOXL", "SOXS"):
        trades = [trade for trade in result.trades if trade.symbol == symbol]
        by_symbol[symbol] = {
            "trade_count": len(trades),
            "win_count": sum(trade.net_pnl >= 0 for trade in trades),
            "loss_count": sum(trade.net_pnl < 0 for trade in trades),
            "net_pnl": round(sum(trade.net_pnl for trade in trades), 2),
            "exit_reasons": dict(Counter(trade.exit_reason for trade in trades)),
        }
    return {
        "net_return_pct": round(result.net_return_pct, 4),
        "net_profit": round(result.net_ending_capital - result.initial_capital, 2),
        "trade_count": result.trade_count,
        "win_count": result.win_count,
        "loss_count": result.loss_count,
        "commission_paid": round(result.total_commission, 2),
        "slippage_cost": round(result.total_slippage_cost, 2),
        "spread_cost": round(result.total_spread_cost, 2),
        "by_symbol": by_symbol,
    }


def main() -> int:
    require_market_data_source(SIGNAL_ROOT, "SMART")
    require_market_data_source(FILL_ROOT, "SMART")
    signal_bars = {
        symbol: load_bars(SIGNAL_ROOT, symbol, "5 mins", duration=DURATION)
        for symbol in SYMBOLS
    }
    fill_bars = {
        symbol: load_bars(FILL_ROOT, symbol, "30 secs", duration=DURATION)
        for symbol in SYMBOLS
    }
    signal_preflight = validate_historical_bar_coverage(
        signal_bars, recent_sessions=2, bar_size="5 mins"
    )
    fill_preflight = validate_historical_bar_coverage(
        fill_bars, recent_sessions=2, bar_size="30 secs"
    )

    baseline = SemiconductorRotationStrategy(
        **ROTATION_HYSTERESIS_V2_PARAMETERS,
        max_notional=5_000.0,
        max_risk_per_trade=120.0,
    )
    candidates = {
        "baseline_v2": baseline,
        "no_exit_hysteresis": replace(baseline, use_exit_hysteresis=False),
        "long_confirm_2": replace(baseline, long_min_confirm_bars=2),
        "long_confirm_3": replace(baseline, long_min_confirm_bars=3),
        "long_strict_1_2x": replace(
            baseline,
            long_min_trend_gap=baseline.long_min_trend_gap * 1.2,
            long_min_vwap_gap=baseline.long_min_vwap_gap * 1.2,
            long_min_score=baseline.long_min_score * 1.2,
        ),
        "long_confirm_2_strict": replace(
            baseline,
            long_min_confirm_bars=2,
            long_min_trend_gap=baseline.long_min_trend_gap * 1.2,
            long_min_vwap_gap=baseline.long_min_vwap_gap * 1.2,
            long_min_score=baseline.long_min_score * 1.2,
        ),
        "min_bars_36": replace(baseline, min_bars=36),
        "cutoff_1200": replace(baseline, entry_fill_cutoff_et_minutes=12 * 60),
        "cutoff_1230": replace(
            baseline, entry_fill_cutoff_et_minutes=12 * 60 + 30
        ),
        "no_hysteresis_long_confirm_2": replace(
            baseline,
            use_exit_hysteresis=False,
            long_min_confirm_bars=2,
        ),
    }

    all_days = sorted(
        {_session_date(bar.time) for bars in signal_bars.values() for bar in bars}
    )
    recent_days = set(all_days[-20:])
    recent_signal = _filter_days(signal_bars, recent_days)
    recent_fill = _filter_days(fill_bars, recent_days)

    results: dict[str, object] = {}
    for index, (name, strategy) in enumerate(candidates.items(), start=1):
        print(f"[{index}/{len(candidates)}] {name}", file=sys.stderr, flush=True)
        evaluation = evaluate_fixed_strategy_walk_forward(
            signal_bars,
            strategy,
            COST_MODEL,
            INITIAL_CAPITAL,
            train_days=252,
            test_days=63,
            step_days=63,
            holdout_days=63,
            entry_fill_model=ENTRY_FILL_MODEL,
            fill_bars_by_symbol=fill_bars,
        )
        fold_returns = [fold.result.net_return_pct for fold in evaluation.folds]
        recent = run_intraday_momentum_backtest(
            recent_signal,
            strategy=strategy,
            cost_model=COST_MODEL,
            initial_capital=INITIAL_CAPITAL,
            entry_fill_model=ENTRY_FILL_MODEL,
            fill_bars_by_symbol=recent_fill,
        )
        results[name] = {
            "oos": {
                "fold_returns_pct": [round(value, 4) for value in fold_returns],
                "mean_return_pct": round(fmean(fold_returns), 4),
                "minimum_return_pct": round(min(fold_returns), 4),
                "positive_fold_count": sum(value > 0 for value in fold_returns),
                "fold_count": len(fold_returns),
            },
            "validation_63_sessions": {
                "start": evaluation.holdout_start.isoformat(),
                "end": evaluation.holdout_end.isoformat(),
                **_result_summary(evaluation.holdout),
            },
            "recent_20_sessions": {
                "start": all_days[-20].isoformat(),
                "end": all_days[-1].isoformat(),
                **_result_summary(recent),
            },
        }

    report = {
        "contract": {
            "profile": "rotation-hysteresis-v2",
            "signal_bar_size": "5 mins",
            "fill_bar_size": "30 secs",
            "signal_root": str(SIGNAL_ROOT),
            "fill_root": str(FILL_ROOT),
            "first_session": all_days[0].isoformat(),
            "last_session": all_days[-1].isoformat(),
            "session_count": len(all_days),
            "capital": INITIAL_CAPITAL,
            "max_notional": 5_000.0,
            "max_risk_per_trade": 120.0,
            "commission_per_order": COST_MODEL.commission_per_order,
            "slippage_bps": COST_MODEL.slippage_bps,
            "spread_bps": COST_MODEL.spread_bps,
            "entry_fill_model": ENTRY_FILL_MODEL,
            "data_source": "reuse-data",
        },
        "signal_preflight": signal_preflight,
        "fill_preflight": fill_preflight,
        "candidate_count": len(candidates),
        "results": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
