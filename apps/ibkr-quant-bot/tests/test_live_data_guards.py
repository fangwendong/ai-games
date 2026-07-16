from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from json import loads
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from ibkr_quant_bot.broker import BrokerError
from ibkr_quant_bot.cli import (
    FROZEN_ROTATION_HYSTERESIS_PARAMETERS,
    FROZEN_ROTATION_HYSTERESIS_VERSION,
    NEW_YORK,
    ROTATION_HYSTERESIS_V2_PARAMETERS,
    ROTATION_HYSTERESIS_V2_VERSION,
    _build_momentum_strategy,
    _build_parser,
    _completed_bars_since_entry,
    _daily_entry_count,
    _daily_entry_limit_reached,
    _fresh_historical_bars,
    _has_price_scale_discontinuity,
    _is_market_hours,
    _latest_entry_time,
    _load_intraday_market_data,
    _load_market_data_exchange,
    _marketable_buy_limit_price,
    _market_data_exchange_state_path,
    _orders_state_path,
    _record_daily_entry,
    _record_order_state,
    _should_flatten,
    _strategy_quote,
    _trade_filled_quantity,
    _trade_lifecycle,
)
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import Bar, MarketSession, Quote, TradeRequest


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
        exchange: str = "SMART",
    ) -> list[Bar]:
        return self.bars

    def live_quote(self, symbol: str, *, exchange: str = "SMART") -> Quote:
        self.live_quote_called = True
        return Quote(symbol=symbol, bid=10.0, ask=10.1, last=10.05, close=10.0)

    def quote(self, symbol: str, *, exchange: str = "SMART") -> Quote:
        self.quote_called = True
        return Quote(symbol=symbol, bid=None, ask=None, last=9.9, close=9.8)


class ExchangeBroker:
    def __init__(
        self,
        missing: set[tuple[str, str]] | None = None,
        quote_missing: set[tuple[str, str]] | None = None,
    ):
        self.missing = missing or set()
        self.quote_missing = quote_missing or set()
        self.bar_calls: list[tuple[str, str]] = []
        self.quote_calls: list[tuple[str, str]] = []
        self.quote_group_calls: list[tuple[tuple[str, ...], str, float, int]] = []

    def historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        exchange: str = "SMART",
    ) -> list[Bar]:
        self.bar_calls.append((exchange, symbol))
        if (exchange, symbol) in self.missing:
            return []
        return [
            Bar(
                time=datetime(2026, 7, 15, 11, 55, tzinfo=NEW_YORK),
                open=10,
                high=10.2,
                low=9.9,
                close=10.1,
                volume=100,
            )
        ]

    def live_quote(self, symbol: str, *, exchange: str = "SMART") -> Quote:
        self.quote_calls.append((exchange, symbol))
        if (exchange, symbol) in self.quote_missing:
            raise BrokerError(f"live quote unavailable for {symbol}")
        return Quote(symbol, bid=10.0, ask=10.1, last=10.05, close=10.0)

    def live_quotes(
        self,
        symbols,
        *,
        exchange: str = "SMART",
        window_seconds: float = 3.0,
        max_samples_per_symbol: int = 100,
    ) -> dict[str, Quote]:
        normalized = tuple(symbols)
        self.quote_group_calls.append(
            (normalized, exchange, window_seconds, max_samples_per_symbol)
        )
        return {
            symbol: self.live_quote(symbol, exchange=exchange)
            for symbol in normalized
        }


def make_bar(age: timedelta) -> Bar:
    timestamp = datetime.now(NEW_YORK) - age
    return Bar(time=timestamp, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class LiveDataGuardsTest(unittest.TestCase):
    def test_backtest_commission_matches_live_calibration(self) -> None:
        args = _build_parser().parse_args(["backtest-momentum"])

        self.assertEqual(1.0, args.commission_per_order)

    def test_hysteresis_profile_is_default(self) -> None:
        args = _build_parser().parse_args(["intraday-momentum"])

        strategy = _build_momentum_strategy(args, Settings())

        self.assertTrue(strategy.use_exit_hysteresis)
        self.assertEqual(3, strategy.exit_confirm_bars)
        self.assertEqual(3, strategy.benchmark_exit_confirm_bars)
        self.assertEqual(0.0375, strategy.long_take_profit_pct)
        self.assertEqual(0.03, strategy.profit_lock_activation_pct)
        self.assertEqual(0.006, strategy.profit_lock_drawdown_pct)
        self.assertEqual(13 * 60 + 30, strategy.entry_fill_cutoff_et_minutes)

    def test_frozen_hysteresis_profile_matches_versioned_baseline(self) -> None:
        args = _build_parser().parse_args(
            ["intraday-momentum", "--profile", "rotation-hysteresis-v1"]
        )
        strategy = _build_momentum_strategy(
            args, Settings(max_order_notional=4000, max_risk_per_trade=120)
        )

        self.assertEqual("rotation-hysteresis-v1", FROZEN_ROTATION_HYSTERESIS_VERSION)
        for name, expected in FROZEN_ROTATION_HYSTERESIS_PARAMETERS.items():
            self.assertEqual(expected, getattr(strategy, name), name)
        self.assertEqual(4000, strategy.max_notional)
        self.assertEqual(120, strategy.max_risk_per_trade)
        self.assertIsNone(strategy.profit_lock_activation_pct)

    def test_v2_profile_adds_frozen_profit_lock_and_entry_cutoff(self) -> None:
        args = _build_parser().parse_args(
            ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
        )
        strategy = _build_momentum_strategy(args, Settings())

        self.assertEqual("rotation-hysteresis-v2", ROTATION_HYSTERESIS_V2_VERSION)
        for name, expected in ROTATION_HYSTERESIS_V2_PARAMETERS.items():
            self.assertEqual(expected, getattr(strategy, name), name)

    def test_frozen_hysteresis_rejects_benchmark_override(self) -> None:
        args = _build_parser().parse_args(
            ["intraday-momentum", "--benchmark-symbol", "SPY"]
        )

        with self.assertRaisesRegex(ValueError, "create a new candidate profile"):
            _build_momentum_strategy(args, Settings())

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
        self.assertEqual(0.03, strategy.profit_lock_activation_pct)

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

    def test_completed_only_excludes_forming_live_bar(self) -> None:
        now = datetime(2026, 7, 10, 12, 1, tzinfo=NEW_YORK)
        completed = Bar(
            time=datetime(2026, 7, 10, 11, 55, tzinfo=NEW_YORK),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        forming = Bar(
            time=datetime(2026, 7, 10, 12, 0, tzinfo=NEW_YORK),
            open=2,
            high=2,
            low=2,
            close=2,
            volume=1,
        )
        broker = FakeBroker([completed, forming])

        bars = _fresh_historical_bars(
            broker,
            Settings(trading_mode="live"),
            "SOXL",
            bar_size="5 mins",
            completed_only=True,
            now=now,
        )

        self.assertEqual([completed], bars)

    def test_completed_only_includes_bar_at_close_boundary(self) -> None:
        now = datetime(2026, 7, 10, 12, 5, tzinfo=NEW_YORK)
        closed = Bar(
            time=datetime(2026, 7, 10, 12, 0, tzinfo=NEW_YORK),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        broker = FakeBroker([closed])

        bars = _fresh_historical_bars(
            broker,
            Settings(trading_mode="live"),
            "SOXL",
            bar_size="5 mins",
            completed_only=True,
            now=now,
        )

        self.assertEqual([closed], bars)

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

    def test_early_close_changes_market_and_flatten_windows(self) -> None:
        session = MarketSession(
            session_date=datetime(2026, 11, 27).date(),
            opens_at=datetime(2026, 11, 27, 9, 30, tzinfo=NEW_YORK),
            closes_at=datetime(2026, 11, 27, 13, 0, tzinfo=NEW_YORK),
        )
        settings = Settings(flatten_before_close_minutes=10)

        self.assertTrue(
            _is_market_hours(datetime(2026, 11, 27, 12, 55, tzinfo=NEW_YORK), session)
        )
        self.assertFalse(
            _is_market_hours(datetime(2026, 11, 27, 13, 1, tzinfo=NEW_YORK), session)
        )
        self.assertTrue(
            _should_flatten(
                settings,
                datetime(2026, 11, 27, 12, 50, tzinfo=NEW_YORK),
                session,
            )
        )

    def test_reverse_split_scale_discontinuity_is_detected(self) -> None:
        bars = [
            Bar(
                time=datetime(2026, 7, 10, 9, 30, tzinfo=NEW_YORK),
                open=50,
                high=51,
                low=49,
                close=50,
                volume=1,
            )
        ]

        self.assertTrue(
            _has_price_scale_discontinuity(
                Quote("SOXS", bid=50, ask=51, last=50, close=10), bars
            )
        )
        self.assertFalse(
            _has_price_scale_discontinuity(
                Quote("SOXS", bid=50, ask=51, last=50, close=49), bars
            )
        )

    def test_live_strategy_forces_live_quote(self) -> None:
        settings = Settings(trading_mode="live")
        broker = FakeBroker()

        quote = _strategy_quote(broker, settings, "SOXL")

        self.assertTrue(broker.live_quote_called)
        self.assertFalse(broker.quote_called)
        self.assertEqual(10.05, quote.last)

    def test_intraday_market_data_pins_smart_when_all_symbols_pass(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live",
                state_dir=tmpdir,
                arca_fallback_enabled=True,
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(["intraday-momentum"]), settings
            )
            now = datetime(2026, 7, 15, 12, 0, tzinfo=NEW_YORK)
            session = MarketSession(
                now.date(),
                now.replace(hour=9, minute=30),
                now.replace(hour=16, minute=0),
            )
            broker = ExchangeBroker()

            exchange, bars, quotes = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

            self.assertEqual("SMART", exchange)
            self.assertEqual({"QQQ", "SOXL", "SOXS"}, set(bars))
            self.assertEqual(set(bars), set(quotes))
            self.assertEqual("SMART", _load_market_data_exchange(settings, now))
            self.assertTrue(_market_data_exchange_state_path(settings, now).exists())
            self.assertNotIn("ARCA", {value for value, _ in broker.bar_calls})
            self.assertEqual(
                [(("QQQ", "SOXL", "SOXS"), "SMART", 3.0, 100)],
                broker.quote_group_calls,
            )

    def test_intraday_market_data_falls_back_as_one_group_and_stays_pinned(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live",
                state_dir=tmpdir,
                arca_fallback_enabled=True,
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(["intraday-momentum"]), settings
            )
            now = datetime(2026, 7, 15, 12, 0, tzinfo=NEW_YORK)
            session = MarketSession(
                now.date(),
                now.replace(hour=9, minute=30),
                now.replace(hour=16, minute=0),
            )
            broker = ExchangeBroker({("SMART", "SOXS")})

            exchange, bars, quotes = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

            self.assertEqual("ARCA", exchange)
            self.assertEqual({"QQQ", "SOXL", "SOXS"}, set(bars))
            self.assertEqual(
                {("SMART", "QQQ"), ("SMART", "SOXL"), ("SMART", "SOXS")},
                set(broker.quote_calls),
            )
            self.assertEqual("ARCA", _load_market_data_exchange(settings, now))

            broker.missing.clear()
            broker.bar_calls.clear()
            broker.quote_calls.clear()
            pinned, _, _ = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

            self.assertEqual("ARCA", pinned)
            self.assertEqual(
                {("ARCA", "QQQ"), ("ARCA", "SOXL"), ("ARCA", "SOXS")},
                set(broker.bar_calls),
            )
            self.assertNotIn("SMART", {value for value, _ in broker.bar_calls})
            self.assertEqual(
                {("SMART", "QQQ"), ("SMART", "SOXL"), ("SMART", "SOXS")},
                set(broker.quote_calls),
            )

    def test_intraday_market_data_never_falls_back_smart_quotes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                trading_mode="live",
                state_dir=tmpdir,
                arca_fallback_enabled=True,
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(["intraday-momentum"]), settings
            )
            now = datetime(2026, 7, 15, 12, 0, tzinfo=NEW_YORK)
            session = MarketSession(
                now.date(),
                now.replace(hour=9, minute=30),
                now.replace(hour=16, minute=0),
            )
            broker = ExchangeBroker(quote_missing={("SMART", "SOXS")})

            with self.assertRaisesRegex(BrokerError, "SMART live quote group"):
                _load_intraday_market_data(
                    broker, settings, strategy, session, now
                )

            self.assertEqual([], broker.bar_calls)
            self.assertNotIn("ARCA", {value for value, _ in broker.quote_calls})

    def test_intraday_market_data_does_not_fallback_when_disabled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(trading_mode="live", state_dir=tmpdir)
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(["intraday-momentum"]), settings
            )
            now = datetime(2026, 7, 15, 12, 0, tzinfo=NEW_YORK)
            session = MarketSession(
                now.date(),
                now.replace(hour=9, minute=30),
                now.replace(hour=16, minute=0),
            )
            broker = ExchangeBroker({("SMART", "SOXS")})

            with self.assertRaisesRegex(BrokerError, "SMART"):
                _load_intraday_market_data(
                    broker, settings, strategy, session, now
                )

            self.assertIsNone(_load_market_data_exchange(settings, now))
            self.assertNotIn("ARCA", {value for value, _ in broker.bar_calls})

    def test_broker_live_quote_rejects_close_only_quote(self) -> None:
        from ibkr_quant_bot.broker import IbkrBroker

        broker = object.__new__(IbkrBroker)
        broker._quote_with_type = lambda symbol, market_data_type, exchange="SMART": Quote(  # type: ignore[attr-defined]
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

            now = datetime(2026, 7, 10, 12, 5, tzinfo=NEW_YORK)
            _record_daily_entry(
                settings,
                request,
                now=now,
                filled_quantity=3.0,
                average_fill_price=101.25,
                strategy_version="rotation-hysteresis-v2",
            )

            path = next(Path(tmpdir).glob("entries-*.json"))
            row = loads(path.read_text())["entries"][0]
            self.assertEqual(3.0, row["filled_quantity"])
            self.assertEqual(101.25, row["average_fill_price"])
            self.assertEqual("rotation-hysteresis-v2", row["strategy_version"])
            self.assertEqual("DAY", row["time_in_force"])
            self.assertEqual(now, _latest_entry_time(settings, "SOXL", now))

    def test_completed_bars_since_entry_excludes_forming_and_pre_entry_bars(
        self,
    ) -> None:
        entry = datetime(2026, 7, 10, 12, 5, 11, tzinfo=NEW_YORK)
        now = datetime(2026, 7, 10, 12, 16, tzinfo=NEW_YORK)
        bars = [
            Bar(
                time=datetime(2026, 7, 10, 12, minute, tzinfo=NEW_YORK),
                open=100,
                high=101,
                low=99,
                close=100 + minute / 100,
                volume=1,
            )
            for minute in (0, 5, 10, 15)
        ]

        completed = _completed_bars_since_entry(bars, entry, now)

        self.assertEqual([bars[1], bars[2]], completed)

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
