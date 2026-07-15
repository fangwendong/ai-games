from __future__ import annotations

import unittest
from datetime import date, datetime

from ibkr_quant_bot.backtest import BacktestCostModel, BacktestTrade
from ibkr_quant_bot.gap_reversion_research import (
    GapReversionConfig,
    GapReversionTrade,
)
from ibkr_quant_bot.hybrid_state_research import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    replay_earliest_signal,
)


class HybridStateResearchTest(unittest.TestCase):
    def test_v2_has_priority_and_gap_only_fills_idle_day(self) -> None:
        v2 = BacktestTrade(
            symbol="SOXL",
            entry_date=date(2026, 1, 5),
            exit_date=date(2026, 1, 5),
            shares=10,
            gross_entry_price=100,
            gross_exit_price=101,
            net_entry_price=100,
            net_exit_price=101,
            exit_reason="eod",
            gross_pnl=10,
            net_pnl=8,
            entry_time=datetime(2026, 1, 5, 10),
        )
        gap_same_day = GapReversionTrade(
            symbol="AAA",
            session_date=date(2026, 1, 5),
            gap_down_pct=0.03,
            gap_atr=1,
            entry_time=datetime(2026, 1, 5, 10),
            exit_time=datetime(2026, 1, 5, 15),
            shares=10,
            raw_entry_price=10,
            raw_exit_price=11,
            stop_distance=1,
            exit_reason="gap_fill",
            net_pnl=8,
        )
        gap_idle_day = GapReversionTrade(
            **{
                **gap_same_day.__dict__,
                "session_date": date(2026, 1, 6),
                "entry_time": datetime(2026, 1, 6, 10),
                "exit_time": datetime(2026, 1, 6, 15),
            }
        )
        config = GapReversionConfig(
            strategy_version="gap",
            symbols=("AAA",),
            minimum_average_daily_volume=0,
        )

        result = replay_earliest_signal(
            (v2,),
            (gap_same_day, gap_idle_day),
            config,
            BacktestCostModel(1, 0, 0),
        )
        self.assertEqual(STRATEGY_NAME, result.strategy_name)
        self.assertEqual(STRATEGY_VERSION, result.strategy_version)

        self.assertEqual(2, result.trade_count)
        self.assertEqual(1, result.gap_trade_count)
        self.assertEqual(["SOXL", "AAA"], [trade.symbol for trade in result.trades])

    def test_gap_preempts_a_later_v2_entry_without_future_knowledge(self) -> None:
        v2 = BacktestTrade(
            symbol="SOXL",
            entry_date=date(2026, 1, 5),
            exit_date=date(2026, 1, 5),
            shares=10,
            gross_entry_price=100,
            gross_exit_price=101,
            net_entry_price=100,
            net_exit_price=101,
            exit_reason="eod",
            gross_pnl=10,
            net_pnl=8,
            entry_time=datetime(2026, 1, 5, 11),
        )
        gap = GapReversionTrade(
            symbol="AAA",
            session_date=date(2026, 1, 5),
            gap_down_pct=0.03,
            gap_atr=1,
            entry_time=datetime(2026, 1, 5, 10),
            exit_time=datetime(2026, 1, 5, 15),
            shares=10,
            raw_entry_price=10,
            raw_exit_price=11,
            stop_distance=1,
            exit_reason="gap_fill",
            net_pnl=8,
        )
        config = GapReversionConfig(
            strategy_version="gap",
            symbols=("AAA",),
            minimum_average_daily_volume=0,
        )

        result = replay_earliest_signal(
            (v2,), (gap,), config, BacktestCostModel(1, 0, 0)
        )

        self.assertEqual(["AAA"], [trade.symbol for trade in result.trades])


if __name__ == "__main__":
    unittest.main()
