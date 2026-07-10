from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ibkr_quant_bot.backtest import BacktestCostModel, run_intraday_momentum_backtest
from ibkr_quant_bot.models import Bar
from ibkr_quant_bot.strategy import IntradayMomentumStrategy, SemiconductorRotationStrategy


def make_trending_bars(symbol: str, start_price: float = 100.0) -> list[Bar]:
    start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    price = start_price
    for index in range(90):
        time = start + timedelta(minutes=5 * index)
        open_price = price
        close_price = price + 1.0
        bars.append(
            Bar(
                time=time,
                open=open_price,
                high=close_price + 0.4,
                low=open_price - 0.3,
                close=close_price,
                volume=1000 + index,
            )
        )
        price = close_price
    return bars


def make_benchmark_bars(start_price: float = 300.0) -> list[Bar]:
    start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    price = start_price
    for index in range(90):
        time = start + timedelta(minutes=5 * index)
        open_price = price
        close_price = price + 0.5
        bars.append(
            Bar(
                time=time,
                open=open_price,
                high=close_price + 0.3,
                low=open_price - 0.2,
                close=close_price,
                volume=2000 + index,
            )
        )
        price = close_price
    return bars


class BacktestCostTest(unittest.TestCase):
    def test_cost_model_worsens_net_return(self) -> None:
        strategy = IntradayMomentumStrategy(symbols=("SOXL",), require_vwap_confirmation=False)
        bars_by_symbol = {"SOXL": make_trending_bars("SOXL"), "QQQ": make_benchmark_bars()}

        result = run_intraday_momentum_backtest(
            bars_by_symbol=bars_by_symbol,
            strategy=strategy,
            cost_model=BacktestCostModel(commission_per_order=1.0, slippage_bps=2.0, spread_bps=2.0),
            initial_capital=1000.0,
        )

        self.assertGreater(result.trade_count, 0)
        self.assertGreater(result.gross_return_pct, result.net_return_pct)
        self.assertGreater(result.total_commission, 0.0)
        self.assertGreater(result.total_slippage_cost, 0.0)
        self.assertGreater(result.total_spread_cost, 0.0)

    def test_rotation_strategy_trades_both_regimes(self) -> None:
        strategy = SemiconductorRotationStrategy()
        bars_by_symbol = {
            "SOXL": make_trending_bars("SOXL"),
            "SOXS": make_trending_bars("SOXS"),
            "QQQ": make_benchmark_bars(),
        }

        result = run_intraday_momentum_backtest(
            bars_by_symbol=bars_by_symbol,
            strategy=strategy,
            cost_model=BacktestCostModel(commission_per_order=1.0, slippage_bps=2.0, spread_bps=2.0),
            initial_capital=1000.0,
        )

        self.assertGreater(result.trade_count, 0)
        self.assertGreater(result.gross_return_pct, result.net_return_pct)


if __name__ == "__main__":
    unittest.main()
