from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ibkr_quant_bot.gap_reversion_research import (
    GapReversionConfig,
    run_gap_reversion_backtest,
)
from ibkr_quant_bot.models import Bar


NEW_YORK = ZoneInfo("America/New_York")


def session(day: int, open_price: float, *, recover: bool) -> list[Bar]:
    start = datetime(2026, 1, 5, 9, 30, tzinfo=NEW_YORK) + timedelta(days=day)
    rows = []
    for index in range(78):
        price = open_price + (0.03 * index if recover else -0.01 * index)
        rows.append(
            Bar(
                time=start + timedelta(minutes=5 * index),
                open=price,
                high=price + 0.08,
                low=price - 0.08,
                close=price + (0.05 if recover else -0.02),
                volume=100_000,
            )
        )
    return rows


def config() -> GapReversionConfig:
    return GapReversionConfig(
        strategy_version="test",
        symbols=("AAA",),
        statistics_lookback=2,
        minimum_gap_down_pct=0.01,
        minimum_gap_atr=0.1,
        minimum_average_daily_volume=0,
        minimum_price=0,
        recovery_confirm_bars=2,
        maximum_benchmark_gap_down_pct=1,
    )


class GapReversionResearchTest(unittest.TestCase):
    def test_recovery_fills_on_next_bar_and_exits_at_gap_fill(self) -> None:
        stock = session(0, 20, recover=False) + session(1, 20, recover=False)
        stock += session(2, 18, recover=True)
        benchmark = session(0, 100, recover=True) + session(1, 100, recover=True)
        benchmark += session(2, 100, recover=True)

        result = run_gap_reversion_backtest(
            {"AAA": stock, "QQQ": benchmark}, config()
        )

        self.assertEqual(1, result.trade_count)
        self.assertGreater(result.trades[0].entry_time.minute, 30)
        self.assertEqual("gap_fill", result.trades[0].exit_reason)

    def test_no_gap_means_no_trade(self) -> None:
        stock = sum(
            (session(day, 20 + 2.36 * day, recover=True) for day in range(3)), []
        )
        benchmark = sum((session(day, 100, recover=True) for day in range(3)), [])

        result = run_gap_reversion_backtest(
            {"AAA": stock, "QQQ": benchmark}, config()
        )

        self.assertEqual(0, result.trade_count)


if __name__ == "__main__":
    unittest.main()
