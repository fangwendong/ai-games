from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

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
