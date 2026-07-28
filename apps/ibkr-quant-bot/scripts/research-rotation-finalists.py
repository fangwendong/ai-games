#!/usr/bin/env python3
"""Stress-test the V2 baseline and immediate-exit finalist."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from statistics import fmean

from ibkr_quant_bot.backtest import (
    BacktestCostModel,
    BacktestResult,
    evaluate_fixed_strategy_walk_forward,
)
from ibkr_quant_bot.cli import ROTATION_HYSTERESIS_V2_PARAMETERS
from ibkr_quant_bot.historical_cache import load_bars, require_market_data_source
from ibkr_quant_bot.strategy import SemiconductorRotationStrategy


SIGNAL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/5-min-rth")
FILL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth")
SYMBOLS = ("SOXL", "SOXS", "QQQ")


def _trade_drawdown(result: BacktestResult) -> dict[str, float]:
    equity = result.initial_capital
    peak = equity
    maximum = 0.0
    for trade in result.trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return {
        "trade_level_max_drawdown": round(maximum, 2),
        "trade_level_max_drawdown_pct": round(
            maximum / result.initial_capital * 100.0, 4
        ),
    }


def main() -> int:
    require_market_data_source(SIGNAL_ROOT, "SMART")
    require_market_data_source(FILL_ROOT, "SMART")
    signal_bars = {
        symbol: load_bars(SIGNAL_ROOT, symbol, "5 mins", duration="930 D")
        for symbol in SYMBOLS
    }
    fill_bars = {
        symbol: load_bars(FILL_ROOT, symbol, "30 secs", duration="930 D")
        for symbol in SYMBOLS
    }
    baseline = SemiconductorRotationStrategy(
        **ROTATION_HYSTERESIS_V2_PARAMETERS,
        max_notional=5_000.0,
        max_risk_per_trade=120.0,
    )
    strategies = {
        "baseline_v2": baseline,
        "immediate_exit_v3": replace(baseline, use_exit_hysteresis=False),
        "v3_two_bar_momentum_veto": replace(
            baseline,
            use_exit_hysteresis=False,
            entry_momentum_lookback_bars=2,
        ),
    }
    scenarios = {
        "live_aligned": {
            "entry_fill_model": "open-pullback",
            "cost_model": BacktestCostModel(
                commission_per_order=1.0,
                slippage_bps=1.0,
                spread_bps=1.0,
            ),
        },
        "double_cost": {
            "entry_fill_model": "open-pullback",
            "cost_model": BacktestCostModel(
                commission_per_order=2.0,
                slippage_bps=2.0,
                spread_bps=2.0,
            ),
        },
        "worst_case_fill": {
            "entry_fill_model": "worst-case",
            "cost_model": BacktestCostModel(
                commission_per_order=1.0,
                slippage_bps=1.0,
                spread_bps=1.0,
            ),
        },
    }
    report: dict[str, object] = {}
    total = len(strategies) * len(scenarios)
    index = 0
    for scenario_name, scenario in scenarios.items():
        scenario_results: dict[str, object] = {}
        for strategy_name, strategy in strategies.items():
            index += 1
            print(
                f"[{index}/{total}] {scenario_name}/{strategy_name}",
                file=sys.stderr,
                flush=True,
            )
            evaluation = evaluate_fixed_strategy_walk_forward(
                signal_bars,
                strategy,
                scenario["cost_model"],
                10_000.0,
                train_days=252,
                test_days=63,
                step_days=63,
                holdout_days=63,
                entry_fill_model=scenario["entry_fill_model"],
                fill_bars_by_symbol=fill_bars,
            )
            fold_returns = [
                round(fold.result.net_return_pct, 4)
                for fold in evaluation.folds
            ]
            holdout = evaluation.holdout
            scenario_results[strategy_name] = {
                "fold_returns_pct": fold_returns,
                "mean_oos_return_pct": round(fmean(fold_returns), 4),
                "minimum_oos_return_pct": min(fold_returns),
                "positive_folds": sum(value > 0 for value in fold_returns),
                "validation_63_return_pct": round(
                    holdout.net_return_pct, 4
                ),
                "validation_63_trade_count": holdout.trade_count,
                "validation_63_win_count": holdout.win_count,
                "validation_63_loss_count": holdout.loss_count,
                **_trade_drawdown(holdout),
            }
        report[scenario_name] = scenario_results
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
