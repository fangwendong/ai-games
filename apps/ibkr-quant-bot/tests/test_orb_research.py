from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ibkr_quant_bot.models import Bar
from ibkr_quant_bot.orb_research import (
    OrbResearchConfig,
    evaluate_chronological_splits,
    run_orb_research_backtest,
)


NEW_YORK = ZoneInfo("America/New_York")


def make_session(
    day_offset: int,
    *,
    opening_volume: float,
    breakout: bool,
    base_price: float = 10.0,
) -> list[Bar]:
    start = datetime(2026, 1, 5, 9, 30, tzinfo=NEW_YORK) + timedelta(
        days=day_offset
    )
    rows: list[Bar] = []
    for index in range(78):
        price = base_price + index * 0.001
        close = price + 0.02
        high = close + 0.01
        if index == 0:
            close = base_price + 0.05
            high = base_price + 0.10
        elif index == 1 and breakout:
            close = base_price + 0.12
            high = base_price + 0.13
        elif index == 2 and breakout:
            price = base_price + 0.11
            close = base_price + 0.14
            high = base_price + 0.15
        rows.append(
            Bar(
                time=start + timedelta(minutes=5 * index),
                open=price,
                high=high,
                low=price - 0.03,
                close=close,
                volume=opening_volume if index == 0 else 20_000,
            )
        )
    return rows


def config(*symbols: str, maximum_ranked_candidates: int = 3) -> OrbResearchConfig:
    return OrbResearchConfig(
        strategy_version="orb-test",
        symbols=tuple(symbols),
        relative_volume_lookback=2,
        minimum_relative_volume=1.0,
        minimum_average_daily_volume=0,
        minimum_atr=0,
        maximum_ranked_candidates=maximum_ranked_candidates,
        atr_stop_multiple=0.1,
        commission_per_order=1,
        slippage_bps=1,
        spread_bps=1,
    )


class OrbResearchBacktestTest(unittest.TestCase):
    def test_close_confirmed_breakout_fills_at_next_bar_open(self) -> None:
        bars = []
        bars.extend(make_session(0, opening_volume=100, breakout=False))
        bars.extend(make_session(1, opening_volume=100, breakout=False))
        bars.extend(make_session(2, opening_volume=300, breakout=True))

        result = run_orb_research_backtest({"AAA": bars}, config("AAA"))

        self.assertEqual(1, result.trade_count)
        trade = result.trades[0]
        self.assertEqual("AAA", trade.symbol)
        self.assertEqual(10.11, trade.raw_entry_price)
        self.assertEqual(9 * 60 + 40, trade.entry_time.hour * 60 + trade.entry_time.minute)
        self.assertLess(trade.net_pnl, trade.shares * (trade.raw_exit_price - 10.11))

    def test_only_top_ranked_relative_volume_candidate_is_considered(self) -> None:
        low_rvol = []
        high_rvol = []
        for day in range(2):
            low_rvol.extend(make_session(day, opening_volume=100, breakout=False))
            high_rvol.extend(
                make_session(day, opening_volume=100, breakout=False, base_price=20)
            )
        low_rvol.extend(make_session(2, opening_volume=150, breakout=True))
        high_rvol.extend(
            make_session(2, opening_volume=400, breakout=True, base_price=20)
        )

        result = run_orb_research_backtest(
            {"LOW": low_rvol, "HIGH": high_rvol},
            config("LOW", "HIGH", maximum_ranked_candidates=1),
        )

        self.assertEqual(1, result.trade_count)
        self.assertEqual("HIGH", result.trades[0].symbol)

    def test_bearish_opening_range_is_not_traded(self) -> None:
        bars = []
        bars.extend(make_session(0, opening_volume=100, breakout=False))
        bars.extend(make_session(1, opening_volume=100, breakout=False))
        current = make_session(2, opening_volume=300, breakout=True)
        first = current[0]
        current[0] = Bar(
            time=first.time,
            open=10.1,
            high=10.11,
            low=9.9,
            close=10.0,
            volume=first.volume,
        )
        bars.extend(current)

        result = run_orb_research_backtest({"AAA": bars}, config("AAA"))

        self.assertEqual(0, result.trade_count)

    def test_bearish_benchmark_blocks_long_entry(self) -> None:
        bars = []
        benchmark = []
        for day in range(3):
            bars.extend(
                make_session(
                    day,
                    opening_volume=100 if day < 2 else 300,
                    breakout=day == 2,
                )
            )
            session = make_session(
                day,
                opening_volume=100,
                breakout=False,
                base_price=20,
            )
            if day == 2:
                first = session[0]
                session[0] = Bar(
                    time=first.time,
                    open=20.2,
                    high=20.21,
                    low=19.9,
                    close=20.0,
                    volume=first.volume,
                )
            benchmark.extend(session)
        filtered = OrbResearchConfig(
            **{
                **config("AAA").__dict__,
                "benchmark_symbol": "QQQ",
                "benchmark_filter": "bullish_opening_range",
            }
        )

        result = run_orb_research_backtest(
            {"AAA": bars, "QQQ": benchmark}, filtered
        )

        self.assertEqual(0, result.trade_count)

    def test_chronological_splits_are_ordered_and_non_overlapping(self) -> None:
        bars = []
        for day in range(20):
            bars.extend(
                make_session(
                    day,
                    opening_volume=100 if day < 2 else 300,
                    breakout=day >= 2,
                )
            )

        results = evaluate_chronological_splits({"AAA": bars}, config("AAA"))

        self.assertLess(results["train"].end_date, results["validation"].start_date)
        self.assertLess(
            results["validation"].end_date, results["holdout"].start_date
        )
        self.assertEqual(results["full"].start_date, results["train"].start_date)
        self.assertEqual(results["full"].end_date, results["holdout"].end_date)


if __name__ == "__main__":
    unittest.main()
