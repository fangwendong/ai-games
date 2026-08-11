from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ibkr_quant_bot.backtest import (
    BacktestCostModel,
    ProfitLockRule,
    evaluate_fixed_strategy_walk_forward,
    evaluate_parameter_stability,
    run_intraday_momentum_backtest,
    validate_historical_bar_coverage,
)
from ibkr_quant_bot.models import Bar, Quote, StrategyDecision
from ibkr_quant_bot.strategy import (
    IntradayMomentumStrategy,
    SemiconductorRotationStrategy,
)


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
    def test_rejects_non_positive_bar_size_before_coverage_checks(self) -> None:
        with self.assertRaisesRegex(ValueError, "bar size must be positive"):
            validate_historical_bar_coverage(
                {"SOXL": [Bar(datetime(2026, 8, 10), 1, 1, 1, 1, 1)]},
                bar_size="0 mins",
            )

    def test_historical_preflight_accepts_two_complete_aligned_sessions(self) -> None:
        start = datetime(2026, 7, 10, 13, 30, tzinfo=timezone.utc)
        bars_by_symbol = {}
        for symbol in ("SOXL", "SOXS", "QQQ"):
            bars_by_symbol[symbol] = [
                Bar(
                    time=start + timedelta(days=day, minutes=5 * index),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1,
                )
                for day in (0, 3)
                for index in range(78)
            ]

        report = validate_historical_bar_coverage(bars_by_symbol)

        self.assertEqual("passed", report["status"])
        self.assertEqual("2026-07-13", report["latest_common_session"])

    def test_historical_preflight_rejects_missing_recent_bar(self) -> None:
        start = datetime(2026, 7, 10, 13, 30, tzinfo=timezone.utc)
        complete = [
            Bar(
                time=start + timedelta(days=day, minutes=5 * index),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            )
            for day in (0, 3)
            for index in range(78)
        ]
        bars_by_symbol = {"SOXL": complete, "SOXS": complete, "QQQ": complete[:-1]}

        with self.assertRaisesRegex(ValueError, "found 77"):
            validate_historical_bar_coverage(bars_by_symbol)

    def test_per_share_commission_respects_minimum_and_sell_fee(self) -> None:
        model = BacktestCostModel(
            commission_per_order=0.0,
            commission_per_share=0.005,
            minimum_commission_per_order=1.0,
            sell_fee_per_share=0.0003,
        )

        self.assertEqual(1.0, model.commission(100, side="BUY"))
        self.assertAlmostEqual(5.3, model.commission(1000, side="SELL"))

    def test_profit_lock_exits_at_next_bar_open_after_close_drawdown(self) -> None:
        class HoldStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol, "BUY" if signal else "HOLD", 1 if signal else 0,
                    quote.reference_price, None, "entry", signal, {"score": 1.0}
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "hold", False
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        prices = [(100, 100), (100, 103), (103, 104), (102, 102), (101, 101)]
        bars = [
            Bar(
                time=start + timedelta(minutes=5 * index),
                open=open_price,
                high=max(open_price, close_price),
                low=min(open_price, close_price),
                close=close_price,
                volume=1,
            )
            for index, (open_price, close_price) in enumerate(prices)
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=HoldStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
            profit_lock_rule=ProfitLockRule(activation_pct=0.03, drawdown_pct=0.01),
        )

        self.assertEqual("profit_lock", result.trades[0].exit_reason)
        self.assertEqual(101, result.trades[0].gross_exit_price)

    def test_exit_signal_fills_at_next_bar_open(self) -> None:
        class NextOpenStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY" if signal else "HOLD",
                    quantity=1 if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="entry",
                    signal=signal,
                    meta={"score": 1.0},
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                signal = len(bars) == 2
                return StrategyDecision(
                    symbol=symbol,
                    action="SELL" if signal else "HOLD",
                    quantity=quantity if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="exit",
                    signal=signal,
                    meta={},
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(time=start, open=100, high=101, low=99, close=100, volume=1),
            Bar(
                time=start + timedelta(minutes=5),
                open=101,
                high=111,
                low=100,
                close=110,
                volume=1,
            ),
            Bar(
                time=start + timedelta(minutes=10),
                open=80,
                high=82,
                low=79,
                close=81,
                volume=1,
            ),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=NextOpenStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
        )

        self.assertEqual(1, result.trade_count)
        self.assertEqual(80, result.trades[0].gross_exit_price)
        self.assertEqual("signal", result.trades[0].exit_reason)

    def test_open_pullback_entry_fill_uses_intrabar_low_improvement(self) -> None:
        class EntryStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY" if signal else "HOLD",
                    quantity=1 if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="entry",
                    signal=signal,
                    meta={"score": 1.0},
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol=symbol,
                    action="HOLD",
                    quantity=0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="hold",
                    signal=False,
                    meta={},
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(time=start, open=100, high=100, low=100, close=100, volume=1),
            Bar(
                time=start + timedelta(minutes=5),
                open=100,
                high=101,
                low=90,
                close=99,
                volume=1,
            ),
            Bar(
                time=start + timedelta(minutes=10),
                open=99,
                high=100,
                low=98,
                close=99,
                volume=1,
            ),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=EntryStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
            entry_fill_model="open_pullback",
        )

        self.assertEqual(1, result.trade_count)
        self.assertEqual(98.0, result.trades[0].gross_entry_price)

    def test_worst_case_fill_uses_high_for_buy_and_low_for_sell(self) -> None:
        class WorstCaseStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY" if signal else "HOLD",
                    quantity=1 if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="entry",
                    signal=signal,
                    meta={"score": 1.0},
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                signal = len(bars) == 2
                return StrategyDecision(
                    symbol=symbol,
                    action="SELL" if signal else "HOLD",
                    quantity=quantity if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="exit",
                    signal=signal,
                    meta={},
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(time=start, open=100, high=101, low=99, close=100, volume=1),
            Bar(
                time=start + timedelta(minutes=5),
                open=110,
                high=115,
                low=105,
                close=111,
                volume=1,
            ),
            Bar(
                time=start + timedelta(minutes=10),
                open=85,
                high=88,
                low=80,
                close=81,
                volume=1,
            ),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=WorstCaseStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
            entry_fill_model="worst-case",
        )

        self.assertEqual(1, result.trade_count)
        self.assertEqual(115.0, result.trades[0].gross_entry_price)
        self.assertEqual(80.0, result.trades[0].gross_exit_price)

    def test_mixed_signal_and_fill_bars_keep_signal_logic_on_five_minute_bars(
        self,
    ) -> None:
        class MixedBarStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY" if signal else "HOLD",
                    quantity=1 if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="entry",
                    signal=signal,
                    meta={"score": 1.0, "bars": len(bars)},
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol=symbol,
                    action="HOLD",
                    quantity=0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="hold",
                    signal=False,
                    meta={"bars": len(bars)},
                )

        signal_start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        signal_bars = [
            Bar(signal_start, 100.0, 100.5, 99.5, 100.0, 1000),
            Bar(signal_start + timedelta(minutes=5), 101.0, 101.5, 100.5, 101.0, 1000),
            Bar(signal_start + timedelta(minutes=10), 102.0, 102.5, 101.5, 102.0, 1000),
        ]
        fill_bars = [
            Bar(signal_start + timedelta(minutes=1), 111.0, 111.5, 110.5, 111.0, 100),
            Bar(signal_start + timedelta(minutes=2), 112.0, 112.5, 111.5, 112.0, 100),
            Bar(signal_start + timedelta(minutes=3), 113.0, 113.5, 112.5, 113.0, 100),
            Bar(signal_start + timedelta(minutes=4), 114.0, 114.5, 113.5, 114.0, 100),
            Bar(signal_start + timedelta(minutes=6), 115.0, 115.5, 114.5, 115.0, 100),
            Bar(signal_start + timedelta(minutes=7), 116.0, 116.5, 115.5, 116.0, 100),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": signal_bars, "QQQ": signal_bars},
            strategy=MixedBarStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
            fill_bars_by_symbol={"SOXL": fill_bars, "QQQ": signal_bars},
        )

        self.assertEqual(1, result.trade_count)
        # The 09:30 signal bar is not available until 09:35. The first
        # executable fill bar in this fixture begins at 09:36, so none of the
        # 09:31-09:34 bars may be used even though they sort after 09:30.
        self.assertEqual(115.0, result.trades[0].gross_entry_price)
        self.assertEqual(
            (signal_start + timedelta(minutes=6)).replace(tzinfo=None),
            result.trades[0].entry_time,
        )
        self.assertEqual(102.0, result.trades[0].gross_exit_price)

    def test_completed_signal_can_fill_at_matching_execution_bar_start(self) -> None:
        class FirstCompletedBarStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol=symbol,
                    action="BUY" if signal else "HOLD",
                    quantity=1 if signal else 0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="entry",
                    signal=signal,
                    meta={"score": 1.0},
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol=symbol,
                    action="HOLD",
                    quantity=0,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="hold",
                    signal=False,
                    meta={},
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        signal_bars = [
            Bar(start, 100.0, 101.0, 99.0, 100.0, 1),
            Bar(start + timedelta(minutes=5), 101.0, 102.0, 100.0, 101.0, 1),
        ]
        fill_bars = [
            Bar(
                start + timedelta(minutes=4, seconds=30),
                999.0,
                999.0,
                999.0,
                999.0,
                1,
            ),
            Bar(
                start + timedelta(minutes=5),
                105.0,
                106.0,
                104.0,
                105.0,
                1,
            ),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": signal_bars, "QQQ": signal_bars},
            strategy=FirstCompletedBarStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
            fill_bars_by_symbol={"SOXL": fill_bars, "QQQ": fill_bars},
            signal_bar_size="5 mins",
        )

        self.assertEqual(1, result.trade_count)
        self.assertEqual(105.0, result.trades[0].gross_entry_price)
        self.assertEqual(
            (start + timedelta(minutes=5)).replace(tzinfo=None),
            result.trades[0].entry_time,
        )

    def test_stop_take_uses_close_based_strategy_exit_not_intrabar_high_low(
        self,
    ) -> None:
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
            Bar(
                time=start + timedelta(minutes=5),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1000,
            ),
            Bar(
                time=start + timedelta(minutes=10),
                open=100.0,
                high=115.0,
                low=99.0,
                close=101.0,
                volume=1000,
            ),
        ]

        result = run_intraday_momentum_backtest(
            bars_by_symbol={"SOXL": bars, "QQQ": bars},
            strategy=CloseOnlyStrategy(),
            cost_model=BacktestCostModel(
                commission_per_order=0.0, slippage_bps=0.0, spread_bps=0.0
            ),
            initial_capital=1000.0,
        )

        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0].exit_reason, "eod")
        self.assertEqual(result.trades[0].gross_exit_price, 101.0)

    def test_broker_protective_take_fills_intrabar_at_limit(self) -> None:
        class ProtectiveStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol,
                    "BUY" if signal else "HOLD",
                    1 if signal else 0,
                    quote.reference_price,
                    None,
                    "entry",
                    signal,
                    {"score": 1.0},
                )

            def protective_prices(self, symbol, average_cost, bars):
                return average_cost * 0.98, average_cost * 1.02

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "hold", False
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(start, 100, 100, 100, 100, 1),
            Bar(start + timedelta(minutes=5), 100, 101, 99, 100, 1),
            Bar(start + timedelta(minutes=10), 100, 103, 99, 101, 1),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=ProtectiveStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
        )

        self.assertEqual("protective_take", result.trades[0].exit_reason)
        self.assertEqual(102, result.trades[0].gross_exit_price)

    def test_broker_protective_stop_uses_gap_open(self) -> None:
        class ProtectiveStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol,
                    "BUY" if signal else "HOLD",
                    1 if signal else 0,
                    quote.reference_price,
                    None,
                    "entry",
                    signal,
                    {"score": 1.0},
                )

            def protective_prices(self, symbol, average_cost, bars):
                return average_cost * 0.98, average_cost * 1.02

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "hold", False
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(start, 100, 100, 100, 100, 1),
            Bar(start + timedelta(minutes=5), 100, 101, 99, 100, 1),
            Bar(start + timedelta(minutes=10), 95, 96, 94, 95, 1),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=ProtectiveStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
        )

        self.assertEqual("protective_stop", result.trades[0].exit_reason)
        self.assertEqual(95, result.trades[0].gross_exit_price)

    def test_ambiguous_protective_bar_uses_stop_first(self) -> None:
        class ProtectiveStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                signal = len(bars) == 1
                return StrategyDecision(
                    symbol,
                    "BUY" if signal else "HOLD",
                    1 if signal else 0,
                    quote.reference_price,
                    None,
                    "entry",
                    signal,
                    {"score": 1.0},
                )

            def protective_prices(self, symbol, average_cost, bars):
                return average_cost * 0.98, average_cost * 1.02

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "hold", False
                )

        start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
        bars = [
            Bar(start, 100, 100, 100, 100, 1),
            Bar(start + timedelta(minutes=5), 100, 101, 99, 100, 1),
            Bar(start + timedelta(minutes=10), 100, 103, 97, 100, 1),
        ]

        result = run_intraday_momentum_backtest(
            {"SOXL": bars, "QQQ": bars},
            strategy=ProtectiveStrategy(),
            cost_model=BacktestCostModel(0, 0, 0),
        )

        self.assertEqual("protective_stop", result.trades[0].exit_reason)
        self.assertEqual(98, result.trades[0].gross_exit_price)

    def test_cost_model_worsens_net_return(self) -> None:
        strategy = IntradayMomentumStrategy(
            symbols=("SOXL",), require_vwap_confirmation=False
        )
        bars_by_symbol = {
            "SOXL": make_trending_bars("SOXL"),
            "QQQ": make_benchmark_bars(),
        }

        result = run_intraday_momentum_backtest(
            bars_by_symbol=bars_by_symbol,
            strategy=strategy,
            cost_model=BacktestCostModel(
                commission_per_order=1.0, slippage_bps=2.0, spread_bps=2.0
            ),
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
            cost_model=BacktestCostModel(
                commission_per_order=1.0, slippage_bps=2.0, spread_bps=2.0
            ),
            initial_capital=1000.0,
        )

        self.assertGreater(result.trade_count, 0)
        self.assertGreater(result.gross_return_pct, result.net_return_pct)

    def test_walk_forward_uses_chronological_oos_and_final_holdout(self) -> None:
        bars_by_symbol: dict[str, list[Bar]] = {"SOXL": [], "QQQ": []}
        for day_offset in range(8):
            start = datetime(2026, 6, 1 + day_offset, 14, 30, tzinfo=timezone.utc)
            for index in range(3):
                bar = Bar(
                    time=start + timedelta(minutes=5 * index),
                    open=100 + index,
                    high=101 + index,
                    low=99 + index,
                    close=100.5 + index,
                    volume=1000,
                )
                bars_by_symbol["SOXL"].append(bar)
                bars_by_symbol["QQQ"].append(bar)

        class NoTradeStrategy:
            symbols = ("SOXL",)
            benchmark_symbol = "QQQ"
            min_bars = 1

            def decide(self, symbol, quote, bars, benchmark_bars=None):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "none", False
                )

            def exit_decide(
                self, symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            ):
                return StrategyDecision(
                    symbol, "HOLD", 0, quote.reference_price, None, "none", False
                )

        evaluation = evaluate_fixed_strategy_walk_forward(
            bars_by_symbol,
            NoTradeStrategy(),
            BacktestCostModel(),
            1000,
            train_days=3,
            test_days=2,
            step_days=2,
            holdout_days=1,
        )

        self.assertEqual(2, len(evaluation.folds))
        self.assertLess(evaluation.folds[-1].test_end, evaluation.holdout_start)
        self.assertEqual(datetime(2026, 6, 8).date(), evaluation.holdout_end)

        stability = evaluate_parameter_stability(
            bars_by_symbol,
            {"base": NoTradeStrategy(), "nearby": NoTradeStrategy()},
            BacktestCostModel(),
            1000,
            train_days=3,
            test_days=2,
            step_days=2,
            holdout_days=1,
        )
        self.assertEqual(2, len(stability))
        self.assertTrue(all(item.fold_count == 2 for item in stability))

    def test_walk_forward_rejects_overlapping_oos_folds(self) -> None:
        bars = [
            Bar(
                time=datetime(2026, 6, 1 + offset, 14, 30, tzinfo=timezone.utc),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            )
            for offset in range(5)
        ]
        with self.assertRaisesRegex(ValueError, "do not overlap"):
            evaluate_fixed_strategy_walk_forward(
                {"SOXL": bars, "QQQ": bars},
                IntradayMomentumStrategy(symbols=("SOXL",)),
                BacktestCostModel(),
                1000,
                train_days=1,
                test_days=2,
                step_days=1,
                holdout_days=1,
            )


if __name__ == "__main__":
    unittest.main()
