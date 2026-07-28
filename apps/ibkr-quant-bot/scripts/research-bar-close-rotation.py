#!/usr/bin/env python3
"""Screen bounded rotation candidates with bar-close signal availability."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

from ibkr_quant_bot.backtest import (
    BacktestCostModel,
    evaluate_fixed_strategy_walk_forward,
    run_intraday_momentum_backtest,
)
from ibkr_quant_bot.cli import ROTATION_HYSTERESIS_V2_PARAMETERS
from ibkr_quant_bot.historical_cache import load_bars, require_market_data_source
from ibkr_quant_bot.strategy import SemiconductorRotationStrategy


SIGNAL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/5-min-rth")
FILL_ROOT = Path("/home/fwd/data/ibkr-quant-bot/historical/30-sec-rth")
SYMBOLS = ("SOXL", "SOXS", "QQQ")
NEW_YORK = ZoneInfo("America/New_York")
INITIAL_CAPITAL = 10_000.0
MAX_NOTIONAL = 5_000.0
MAX_RISK_PER_TRADE = 120.0
LIVE_ALIGNED_COST = BacktestCostModel(
    commission_per_order=1.0,
    slippage_bps=1.0,
    spread_bps=1.0,
)


def _load_completed_today(
    root: Path,
    symbol: str,
    bar_size: str,
    duration: timedelta,
    *,
    now: datetime,
) -> list:
    today = now.astimezone(NEW_YORK).date()
    return [
        bar
        for bar in load_bars(root, symbol, bar_size)
        if bar.time.astimezone(NEW_YORK).date() == today
        and bar.time.astimezone(timezone.utc) + duration <= now
    ]


def _trade_summary(result) -> dict[str, object]:
    return {
        "return_pct": round(result.net_return_pct, 4),
        "profit_usd": round(
            result.net_ending_capital - result.initial_capital, 2
        ),
        "trade_count": result.trade_count,
        "wins": result.win_count,
        "losses": result.loss_count,
        "trades": [
            {
                "symbol": trade.symbol,
                "entry_time_utc": (
                    trade.entry_time.replace(tzinfo=timezone.utc).isoformat()
                    if trade.entry_time is not None
                    else None
                ),
                "shares": trade.shares,
                "entry": round(trade.gross_entry_price, 4),
                "exit": round(trade.gross_exit_price, 4),
                "reason": trade.exit_reason,
                "net_pnl": round(trade.net_pnl, 2),
            }
            for trade in result.trades
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--today-root",
        type=Path,
        help="temporary root containing 5m/ and 30s/ intraday caches",
    )
    args = parser.parse_args()

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
        max_notional=MAX_NOTIONAL,
        max_risk_per_trade=MAX_RISK_PER_TRADE,
    )
    immediate = replace(baseline, use_exit_hysteresis=False)
    candidates = {
        "v2_baseline": baseline,
        "v3_immediate_exit": immediate,
        "momentum_2": replace(
            immediate, entry_momentum_lookback_bars=2
        ),
        "momentum_3": replace(
            immediate, entry_momentum_lookback_bars=3
        ),
        "momentum_4": replace(
            immediate, entry_momentum_lookback_bars=4
        ),
        "min_bars_32": replace(immediate, min_bars=32),
        "min_bars_34": replace(immediate, min_bars=34),
        "min_bars_36": replace(immediate, min_bars=36),
        "long_confirm_2": replace(immediate, long_min_confirm_bars=2),
        "both_confirm_plus_1": replace(
            immediate,
            long_min_confirm_bars=2,
            short_min_confirm_bars=3,
        ),
        "long_strict_1_2x": replace(
            immediate,
            long_min_trend_gap=immediate.long_min_trend_gap * 1.2,
            long_min_vwap_gap=immediate.long_min_vwap_gap * 1.2,
            long_min_score=immediate.long_min_score * 1.2,
        ),
        "cutoff_noon": replace(
            immediate, entry_fill_cutoff_et_minutes=12 * 60
        ),
    }

    today_signal = None
    today_fill = None
    today_as_of = None
    if args.today_root is not None:
        require_market_data_source(args.today_root / "5m", "SMART")
        require_market_data_source(args.today_root / "30s", "SMART")
        now = datetime.now(timezone.utc)
        today_as_of = now.astimezone(NEW_YORK).isoformat()
        today_signal = {
            symbol: _load_completed_today(
                args.today_root / "5m",
                symbol,
                "5 mins",
                timedelta(minutes=5),
                now=now,
            )
            for symbol in SYMBOLS
        }
        today_fill = {
            symbol: _load_completed_today(
                args.today_root / "30s",
                symbol,
                "30 secs",
                timedelta(seconds=30),
                now=now,
            )
            for symbol in SYMBOLS
        }

    report: dict[str, object] = {
        "contract": {
            "signal_bar_size": "5 mins",
            "signal_availability": "bar close",
            "fill_bar_size": "30 secs",
            "entry_fill_model": "open-pullback",
            "capital": INITIAL_CAPITAL,
            "max_notional": MAX_NOTIONAL,
            "max_risk_per_trade": MAX_RISK_PER_TRADE,
            "commission_per_order": 1.0,
            "slippage_bps": 1.0,
            "spread_bps": 1.0,
            "today_as_of": today_as_of,
        },
        "candidates": {},
    }
    for index, (name, strategy) in enumerate(candidates.items(), start=1):
        print(
            f"[{index}/{len(candidates)}] {name}",
            file=sys.stderr,
            flush=True,
        )
        evaluation = evaluate_fixed_strategy_walk_forward(
            signal_bars,
            strategy,
            LIVE_ALIGNED_COST,
            INITIAL_CAPITAL,
            train_days=252,
            test_days=63,
            step_days=63,
            holdout_days=63,
            entry_fill_model="open-pullback",
            fill_bars_by_symbol=fill_bars,
            signal_bar_size="5 mins",
        )
        fold_returns = [
            round(fold.result.net_return_pct, 4)
            for fold in evaluation.folds
        ]
        item: dict[str, object] = {
            "development_oos": {
                "fold_returns_pct": fold_returns,
                "mean_return_pct": round(fmean(fold_returns), 4),
                "minimum_return_pct": min(fold_returns),
                "positive_folds": sum(value > 0 for value in fold_returns),
                "fold_count": len(fold_returns),
            },
        }
        if today_signal is not None and today_fill is not None:
            item["today_open_pullback"] = _trade_summary(
                run_intraday_momentum_backtest(
                    today_signal,
                    strategy=strategy,
                    cost_model=LIVE_ALIGNED_COST,
                    initial_capital=INITIAL_CAPITAL,
                    entry_fill_model="open-pullback",
                    fill_bars_by_symbol=today_fill,
                    signal_bar_size="5 mins",
                )
            )
            item["today_worst_case"] = _trade_summary(
                run_intraday_momentum_backtest(
                    today_signal,
                    strategy=strategy,
                    cost_model=LIVE_ALIGNED_COST,
                    initial_capital=INITIAL_CAPITAL,
                    entry_fill_model="worst-case",
                    fill_bars_by_symbol=today_fill,
                    signal_bar_size="5 mins",
                )
            )
        report["candidates"][name] = item

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
