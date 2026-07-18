from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ibkr_quant_bot.models import Bar, Quote
from ibkr_quant_bot.strategy import (
    IntradayMomentumStrategy,
    SemiconductorRotationStrategy,
)


def make_bars(prices: list[float]) -> list[Bar]:
    start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    for index, price in enumerate(prices):
        time = start + timedelta(minutes=index)
        bars.append(
            Bar(
                time=time,
                open=price,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=1000 + index,
            )
        )
    return bars


def make_benchmark_bars(prices: list[float]) -> list[Bar]:
    return make_bars(prices)


def make_bearish_bars(prices: list[float]) -> list[Bar]:
    start = datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    for index, price in enumerate(prices):
        time = start + timedelta(minutes=index)
        bars.append(
            Bar(
                time=time,
                open=price,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=1000 + index,
            )
        )
    return bars


class IntradayMomentumStrategyTest(unittest.TestCase):
    def test_rotation_entry_cutoff_blocks_1330_fill_but_not_1325_fill(self) -> None:
        new_york = ZoneInfo("America/New_York")
        strategy = SemiconductorRotationStrategy(
            entry_fill_cutoff_et_minutes=13 * 60 + 30,
            long_min_score=0.0,
        )
        prices = [100 + index * 0.5 for index in range(31)]
        start = datetime(2026, 7, 14, 10, 55, tzinfo=new_york)
        bars = [
            Bar(
                time=start + timedelta(minutes=5 * index),
                open=price,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=1000 + index,
            )
            for index, price in enumerate(prices)
        ]
        benchmark = [
            Bar(
                time=bar.time,
                open=300 + index,
                high=301 + index,
                low=299 + index,
                close=300 + index,
                volume=2000 + index,
            )
            for index, bar in enumerate(bars)
        ]
        quote = Quote(symbol="SOXL", bid=115, ask=115.1, last=115, close=115)

        allowed = strategy.decide(
            "SOXL", quote, bars[:-1], benchmark_bars=benchmark[:-1]
        )
        blocked = strategy.decide("SOXL", quote, bars, benchmark_bars=benchmark)

        self.assertTrue(allowed.signal)
        self.assertFalse(blocked.signal)
        self.assertTrue(blocked.meta["entry_window_closed"])
        self.assertIn("13:30", blocked.reason)

    def test_decide_returns_buy_for_bullish_series(self) -> None:
        strategy = IntradayMomentumStrategy(min_score=0.0)
        bars = make_bars([100 + i * 0.5 for i in range(30)])
        benchmark_bars = make_benchmark_bars([200 + i * 0.3 for i in range(60)])
        quote = Quote(symbol="SOXL", bid=114.8, ask=115.0, last=114.9, close=114.9)

        decision = strategy.decide("SOXL", quote, bars, benchmark_bars=benchmark_bars)

        self.assertTrue(decision.signal)
        self.assertEqual("BUY", decision.action)
        self.assertGreater(decision.quantity, 0)

    def test_exit_decide_returns_sell_for_bearish_series(self) -> None:
        strategy = IntradayMomentumStrategy(min_score=0.0)
        bars = make_bars([115 - i * 0.5 for i in range(30)])
        quote = Quote(symbol="SOXL", bid=100.0, ask=100.1, last=100.05, close=100.05)

        decision = strategy.exit_decide(
            "SOXL", quote, bars, quantity=3, average_cost=110.0
        )

        self.assertTrue(decision.signal)
        self.assertEqual("SELL", decision.action)
        self.assertEqual(3, decision.quantity)

    def test_exit_keeps_benchmark_confirmation_for_bullish_position(self) -> None:
        strategy = IntradayMomentumStrategy(min_score=0.0)
        bars = make_bars([100 + i * 0.5 for i in range(30)])
        benchmark_bars = make_benchmark_bars([200 + i * 0.3 for i in range(60)])
        quote = Quote(symbol="SOXL", bid=114.4, ask=114.6, last=114.5, close=114.5)

        decision = strategy.exit_decide(
            "SOXL",
            quote,
            bars,
            quantity=3,
            average_cost=114.0,
            benchmark_bars=benchmark_bars,
        )

        self.assertFalse(decision.signal)
        self.assertEqual("HOLD", decision.action)
        self.assertFalse(decision.meta.get("bearish", False))

    def test_exit_hysteresis_ignores_one_bar_dip_but_exits_confirmed_reversal(
        self,
    ) -> None:
        strategy = IntradayMomentumStrategy(
            min_score=0.0,
            require_benchmark_confirmation=False,
            use_exit_hysteresis=True,
            exit_confirm_bars=3,
            exit_reversal_votes=2,
            stop_loss_pct=0.5,
            take_profit_pct=1.0,
            atr_stop_multiple=0.0,
        )
        rising = [100 + i * 0.5 for i in range(30)]
        quote = Quote(symbol="SOXL", bid=110, ask=110.1, last=110, close=110)

        one_bar_dip = strategy.exit_decide(
            "SOXL",
            quote,
            make_bars([*rising, 105]),
            quantity=1,
            average_cost=107,
        )
        confirmed = strategy.exit_decide(
            "SOXL",
            quote,
            make_bars([*rising, 105, 100, 95]),
            quantity=1,
            average_cost=107,
        )

        self.assertFalse(one_bar_dip.signal)
        self.assertTrue(confirmed.signal)
        self.assertTrue(confirmed.meta["bearish"])

    def test_rotation_benchmark_exit_requires_configured_confirmation(self) -> None:
        strategy = SemiconductorRotationStrategy(benchmark_exit_confirm_bars=3)
        strategy._benchmark_bullish = lambda bars: bars[-1].close > 0  # type: ignore[method-assign]

        not_confirmed = make_benchmark_bars([1, 1, -1])
        confirmed = make_benchmark_bars([-1, -1, -1])

        self.assertFalse(strategy._benchmark_reversal_confirmed("SOXL", not_confirmed))
        self.assertTrue(strategy._benchmark_reversal_confirmed("SOXL", confirmed))

    def test_rotation_profit_lock_uses_completed_close_peak(self) -> None:
        strategy = SemiconductorRotationStrategy(
            profit_lock_activation_pct=0.03,
            profit_lock_drawdown_pct=0.006,
        )
        quote = Quote(symbol="SOXL", bid=102, ask=102.1, last=102, close=102)
        bars = make_bars([100, 103.5, 102.8])

        decision = strategy.profit_lock_decide(
            "SOXL", quote, bars, quantity=4, average_cost=100
        )

        self.assertTrue(decision.signal)
        self.assertEqual("SELL", decision.action)
        self.assertEqual(4, decision.quantity)
        self.assertEqual(103.5, decision.meta["profit_lock_peak_close"])

    def test_rotation_profit_lock_waits_until_activation(self) -> None:
        strategy = SemiconductorRotationStrategy(
            profit_lock_activation_pct=0.03,
            profit_lock_drawdown_pct=0.006,
        )
        quote = Quote(symbol="SOXL", bid=99, ask=99.1, last=99, close=99)

        decision = strategy.profit_lock_decide(
            "SOXL", quote, make_bars([100, 102.9, 99]), quantity=4, average_cost=100
        )

        self.assertFalse(decision.signal)

    def test_decide_honors_min_score_threshold(self) -> None:
        strategy = IntradayMomentumStrategy(min_score=1.0)
        bars = make_bars([100 + i * 0.5 for i in range(30)])
        benchmark_bars = make_benchmark_bars([200 + i * 0.3 for i in range(60)])
        quote = Quote(symbol="SOXL", bid=114.8, ask=115.0, last=114.9, close=114.9)

        decision = strategy.decide("SOXL", quote, bars, benchmark_bars=benchmark_bars)

        self.assertFalse(decision.signal)
        self.assertEqual("HOLD", decision.action)

    def test_rotation_strategy_buys_long_symbol_in_bull_regime(self) -> None:
        strategy = SemiconductorRotationStrategy()
        bullish_benchmark = make_benchmark_bars([300 + i * 0.4 for i in range(60)])
        bull_bars = make_bars([100 + i * 0.5 for i in range(40)])
        quote = Quote(symbol="SOXL", bid=119.8, ask=120.0, last=119.9, close=119.9)

        decision = strategy.decide(
            "SOXL", quote, bull_bars, benchmark_bars=bullish_benchmark
        )

        self.assertTrue(decision.signal)
        self.assertEqual("BUY", decision.action)

    def test_rotation_range_gate_blocks_entry_until_completed_range_passes(self) -> None:
        strategy = SemiconductorRotationStrategy(
            benchmark_min_intraday_range=0.0075,
            long_min_score=0.0,
        )
        bull_bars = make_bars([100 + i * 0.5 for i in range(40)])
        quote = Quote(symbol="SOXL", bid=119.8, ask=120.0, last=119.9, close=119.9)
        narrow = make_benchmark_bars([300 + i * 0.01 for i in range(60)])
        wide = [
            Bar(
                time=bar.time,
                open=bar.open,
                high=bar.high if index else 303.0,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for index, bar in enumerate(narrow)
        ]

        blocked = strategy.decide(
            "SOXL", quote, bull_bars, benchmark_bars=narrow
        )
        allowed = strategy.decide("SOXL", quote, bull_bars, benchmark_bars=wide)

        self.assertFalse(blocked.signal)
        self.assertEqual("HOLD", blocked.action)
        self.assertFalse(blocked.meta["benchmark_range_gate_passed"])
        self.assertIn("below minimum", blocked.reason)
        self.assertTrue(allowed.signal)
        self.assertEqual("BUY", allowed.action)
        self.assertTrue(allowed.meta["benchmark_range_gate_passed"])

    def test_rotation_strategy_buys_short_symbol_in_bear_regime(self) -> None:
        strategy = SemiconductorRotationStrategy()
        bearish_benchmark = make_bearish_bars([300 - i * 0.4 for i in range(60)])
        bear_bars = make_bars([100 + i * 0.5 for i in range(40)])
        quote = Quote(symbol="SOXS", bid=119.8, ask=120.0, last=119.9, close=119.9)

        decision = strategy.decide(
            "SOXS", quote, bear_bars, benchmark_bars=bearish_benchmark
        )

        self.assertTrue(decision.signal)
        self.assertEqual("BUY", decision.action)


if __name__ == "__main__":
    unittest.main()
