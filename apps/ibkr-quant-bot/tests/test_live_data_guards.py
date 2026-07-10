from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from json import loads
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from ibkr_quant_bot.broker import BrokerError
from ibkr_quant_bot.cli import (
    NEW_YORK,
    _build_momentum_strategy,
    _build_parser,
    _daily_entry_count,
    _daily_entry_limit_reached,
    _fresh_historical_bars,
    _marketable_buy_limit_price,
    _orders_state_path,
    _record_daily_entry,
    _record_order_state,
    _should_flatten,
    _strategy_quote,
    _trade_filled_quantity,
    _trade_lifecycle,
)
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import Bar, Quote, TradeRequest


class FakeBroker:
    def __init__(self, bars: list[Bar] | None = None):
        self.bars = bars or []
        self.live_quote_called = False
        self.quote_called = False

    def historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
    ) -> list[Bar]:
        return self.bars

    def live_quote(self, symbol: str) -> Quote:
        self.live_quote_called = True
        return Quote(symbol=symbol, bid=10.0, ask=10.1, last=10.05, close=10.0)

    def quote(self, symbol: str) -> Quote:
        self.quote_called = True
        return Quote(symbol=symbol, bid=None, ask=None, last=9.9, close=9.8)


def make_bar(age: timedelta) -> Bar:
    timestamp = datetime.now(NEW_YORK) - age
    return Bar(time=timestamp, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class LiveDataGuardsTest(unittest.TestCase):
    def test_hysteresis_profile_is_default(self) -> None:
        args = _build_parser().parse_args(["intraday-momentum"])

        strategy = _build_momentum_strategy(args, Settings())

        self.assertTrue(strategy.use_exit_hysteresis)
        self.assertEqual(3, strategy.exit_confirm_bars)
        self.assertEqual(3, strategy.benchmark_exit_confirm_bars)
        self.assertEqual(0.0375, strategy.long_take_profit_pct)

    def test_plain_rotation_profile_is_still_available(self) -> None:
        args = _build_parser().parse_args(["intraday-momentum", "--profile", "rotation"])

        strategy = _build_momentum_strategy(args, Settings())

        self.assertFalse(strategy.use_exit_hysteresis)
        self.assertEqual(1, strategy.benchmark_exit_confirm_bars)
        self.assertEqual(0.035, strategy.long_take_profit_pct)

    def test_backtest_uses_hysteresis_profile_by_default(self) -> None:
        args = _build_parser().parse_args(["backtest-momentum"])

        strategy = _build_momentum_strategy(args, Settings())

        self.assertTrue(strategy.use_exit_hysteresis)
        self.assertEqual(0.0375, strategy.long_take_profit_pct)

    def test_live_strategy_rejects_stale_bars(self) -> None:
        settings = Settings(trading_mode="live", live_bar_max_age_seconds=420)
        broker = FakeBroker([make_bar(timedelta(minutes=20))])

        with self.assertRaisesRegex(BrokerError, "stale"):
            _fresh_historical_bars(broker, settings, "SOXL", bar_size="5 mins")

    def test_live_strategy_accepts_recent_bars(self) -> None:
        settings = Settings(trading_mode="live", live_bar_max_age_seconds=420)
        broker = FakeBroker([make_bar(timedelta(minutes=3))])

        bars = _fresh_historical_bars(broker, settings, "SOXL", bar_size="5 mins")

        self.assertEqual(1, len(bars))

    def test_session_filter_excludes_previous_day_bars(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=NEW_YORK)
        previous = Bar(
            time=datetime(2026, 7, 9, 15, 55, tzinfo=NEW_YORK),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        current = Bar(
            time=datetime(2026, 7, 10, 11, 55, tzinfo=NEW_YORK),
            open=2,
            high=2,
            low=2,
            close=2,
            volume=1,
        )
        broker = FakeBroker([previous, current])

        bars = _fresh_historical_bars(
            broker,
            Settings(),
            "SOXL",
            bar_size="5 mins",
            session_only=True,
            now=now,
        )

        self.assertEqual([current], bars)

    def test_flatten_window_blocks_overnight_hold(self) -> None:
        settings = Settings(flatten_before_close_minutes=10)

        self.assertFalse(
            _should_flatten(settings, datetime(2026, 7, 10, 15, 49, tzinfo=NEW_YORK))
        )
        self.assertTrue(
            _should_flatten(settings, datetime(2026, 7, 10, 15, 50, tzinfo=NEW_YORK))
        )

    def test_live_strategy_forces_live_quote(self) -> None:
        settings = Settings(trading_mode="live")
        broker = FakeBroker()

        quote = _strategy_quote(broker, settings, "SOXL")

        self.assertTrue(broker.live_quote_called)
        self.assertFalse(broker.quote_called)
        self.assertEqual(10.05, quote.last)

    def test_broker_live_quote_rejects_close_only_quote(self) -> None:
        from ibkr_quant_bot.broker import IbkrBroker

        broker = object.__new__(IbkrBroker)
        broker._quote_with_type = lambda symbol, market_data_type: Quote(  # type: ignore[attr-defined]
            symbol=symbol,
            bid=None,
            ask=None,
            last=None,
            close=10.0,
        )

        with self.assertRaisesRegex(BrokerError, "live quote unavailable"):
            broker.live_quote("SOXL")

    def test_daily_entry_limit_defaults_to_one(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live", state_dir=tmpdir, max_daily_entries=1
            )
            request = TradeRequest(
                symbol="SOXL",
                action="BUY",
                quantity=5,
                order_type="LMT",
                limit_price=100.0,
            )

            self.assertFalse(_daily_entry_limit_reached(settings))
            _record_daily_entry(settings, request)

            self.assertEqual(1, _daily_entry_count(settings))
            self.assertTrue(_daily_entry_limit_reached(settings))

    def test_daily_entry_record_keeps_fill_details(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live", state_dir=tmpdir, max_daily_entries=1
            )
            request = TradeRequest(
                symbol="SOXL",
                action="BUY",
                quantity=5,
                order_type="LMT",
                limit_price=100.0,
                time_in_force="DAY",
            )

            _record_daily_entry(settings, request, filled_quantity=3.0)

            path = next(Path(tmpdir).glob("entries-*.json"))
            row = loads(path.read_text())["entries"][0]
            self.assertEqual(3.0, row["filled_quantity"])
            self.assertEqual("DAY", row["time_in_force"])

    def test_marketable_buy_limit_uses_offset_and_rounds_up(self) -> None:
        settings = Settings(entry_order_price_offset_bps=5)

        limit_price = _marketable_buy_limit_price(100.001, 99.0, settings)

        self.assertEqual(100.06, limit_price)

    def test_trade_filled_quantity_handles_missing_status(self) -> None:
        trade = SimpleNamespace(orderStatus=SimpleNamespace(filled="2"))

        self.assertEqual(2.0, _trade_filled_quantity(trade))
        self.assertEqual(0.0, _trade_filled_quantity(SimpleNamespace()))

    def test_order_lifecycle_distinguishes_partial_and_rejected(self) -> None:
        partial = SimpleNamespace(
            orderStatus=SimpleNamespace(status="Submitted", filled=2, remaining=3)
        )
        rejected = SimpleNamespace(
            orderStatus=SimpleNamespace(status="Inactive", filled=0, remaining=5)
        )

        self.assertEqual("partially_filled", _trade_lifecycle(partial))
        self.assertEqual("rejected_or_inactive", _trade_lifecycle(rejected))

    def test_nonpositive_daily_entry_limit_is_unlimited(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live", state_dir=tmpdir, max_daily_entries=0
            )
            request = TradeRequest(symbol="SOXL", action="BUY", quantity=5)

            _record_daily_entry(settings, request)

            self.assertEqual(1, _daily_entry_count(settings))
            self.assertFalse(_daily_entry_limit_reached(settings))

    def test_order_state_is_recorded_as_jsonl(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(trading_mode="live", state_dir=tmpdir)
            request = TradeRequest(
                symbol="SOXL",
                action="BUY",
                quantity=5,
                order_type="LMT",
                limit_price=188.12,
            )
            trade = SimpleNamespace(
                order=SimpleNamespace(
                    orderId=123,
                    permId=456,
                    clientId=42,
                    action="BUY",
                    totalQuantity=5,
                    orderType="LMT",
                    lmtPrice=188.12,
                    account="DU123",
                ),
                orderStatus=SimpleNamespace(
                    status="Submitted",
                    filled=0,
                    remaining=5,
                    avgFillPrice=0.0,
                    lastFillPrice=0.0,
                    whyHeld="",
                ),
                fills=[],
                log=[],
            )

            _record_order_state(settings, request, trade)

            path = _orders_state_path(settings)
            self.assertTrue(Path(path).exists())
            row = loads(Path(path).read_text().strip())
            self.assertEqual("SOXL", row["request"]["symbol"])
            self.assertEqual(123, row["order"]["order_id"])
            self.assertEqual(456, row["order"]["perm_id"])
            self.assertEqual("Submitted", row["status"]["status"])
            self.assertEqual("active", row["status"]["lifecycle"])
            self.assertEqual(0, row["status"]["filled"])
            self.assertEqual(5, row["status"]["remaining"])


if __name__ == "__main__":
    unittest.main()
