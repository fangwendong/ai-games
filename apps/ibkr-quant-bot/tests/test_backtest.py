from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ibkr_quant_bot.backtest import BacktestCostModel, run_intraday_momentum_backtest
from ibkr_quant_bot.models import Bar, Quote, StrategyDecision
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
    def test_stop_take_uses_close_based_strategy_exit_not_intrabar_high_low(self) -> None:
        class CloseOnlyStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1
            slow_window = 1
            trend_window = 1
            trend_lookback = 1

            def decide(
                self,
                symbol: str,
                quote: Quote,
                bars: list[Bar],
                benchmark_bars: list[Bar] | None = None,
            ) -> StrategyDecision:
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY",
                    quantity=1,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="test entry",
                    signal=len(bars) == 2,
                    meta={"score": 1.0},
                )

            def exit_decide(
                self,
                symbol: str,
                quote: Quote,
                bars: list[Bar],
                quantity: int,
                average_cost: float,
            ) -> StrategyDecision:
                take_hit = quote.reference_price >= average_cost * 1.10
                return StrategyDecision(
                    symbol=symbol,
                    action="SELL" if take_hit else "HOLD",
                    quantity=quantity if take_hit else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="close-based exit",
                    signal=take_hit,
                    meta={"take_hit": take_hit},
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(time=start, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
            Bar(time=start + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
            Bar(time=start + timedelta(minutes=10), open=100.0, high=115.0, low=99.0, close=101.0, volume=1000),
        ]

        result = run_intraday_momentum_backtest(
            bars_by_symbol={"SOXL": bars, "QQQ": bars},
            strategy=CloseOnlyStrategy(),
            cost_model=BacktestCostModel(commission_per_order=0.0, slippage_bps=0.0, spread_bps=0.0),
            initial_capital=1000.0,
        )

        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0].exit_reason, "eod")
        self.assertEqual(result.trades[0].gross_exit_price, 101.0)

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
