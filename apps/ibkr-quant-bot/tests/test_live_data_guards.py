from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
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
    ROTATION_HYSTERESIS_V3_PARAMETERS,
    ROTATION_HYSTERESIS_V3_VERSION,
    ROTATION_HYSTERESIS_V4_PARAMETERS,
    ROTATION_HYSTERESIS_V4_VERSION,
    ROTATION_RANGE_GATED_V1_PARAMETERS,
    ROTATION_RANGE_GATED_V1_VERSION,
    _backtest_core_parameters_report,
    _build_momentum_strategy,
    _build_parser,
    _available_cash_notional,
    _benchmark_quote_summary,
    _completed_bars_since_entry,
    _cancel_orphaned_strategy_entry_orders,
    _daily_entry_count,
    _daily_entry_limit_reached,
    _fresh_historical_bars,
    _flatten_strategy_positions_if_due,
    _ensure_protective_oca,
    _ensure_positions_protected_before_market_data,
    _has_price_scale_discontinuity,
    _is_market_hours,
    _latest_entry_time,
    _latest_entry_protective_prices,
    _latest_trade_price_fields,
    _live_context_cache_path,
    _load_intraday_market_data,
    _load_market_data_exchange,
    _marketable_buy_limit_price,
    _market_data_exchange_state_path,
    _orders_state_path,
    _protective_order_display,
    _quote_timing_fields,
    _record_daily_entry,
    _record_order_state,
    _resolve_backtest_entry_fill_model,
    _run_live_context_cache,
    _run_live_quote_cache,
    _should_flatten,
    _strategy_quote,
    _tradable_capital_snapshot,
    _trade_filled_quantity,
    _trade_lifecycle,
)
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import Bar, MarketSession, Quote, TradeRequest
from ibkr_quant_bot.quote_cache import QuoteCacheWriter
from ibkr_quant_bot.market_context_cache import write_market_context_cache


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
        self.quote_group_calls: list[tuple[tuple[str, ...], str]] = []

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

    def live_quote_snapshots(
        self,
        symbols,
        *,
        exchange: str = "SMART",
    ) -> dict[str, Quote]:
        normalized = tuple(symbols)
        self.quote_group_calls.append((normalized, exchange))
        return {
            symbol: self.live_quote(symbol, exchange=exchange)
            for symbol in normalized
        }


def make_bar(age: timedelta) -> Bar:
    timestamp = datetime.now(NEW_YORK) - age
    return Bar(time=timestamp, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class LiveDataGuardsTest(unittest.TestCase):
    def test_available_cash_notional_uses_lower_cash_or_available_funds(self) -> None:
        rows = [
            {
                "account": "U123",
                "tag": "TotalCashValue",
                "value": "4412.25",
                "currency": "USD",
            },
            {
                "account": "U123",
                "tag": "AvailableFunds",
                "value": "4388.50",
                "currency": "USD",
            },
            {
                "account": "U123",
                "tag": "BuyingPower",
                "value": "17554.00",
                "currency": "USD",
            },
        ]

        self.assertEqual(4388.50, _available_cash_notional(rows))

    def test_available_cash_notional_rejects_missing_or_multiple_accounts(self) -> None:
        with self.assertRaisesRegex(BrokerError, "missing USD account balance fields"):
            _available_cash_notional(
                [
                    {
                        "account": "U123",
                        "tag": "TotalCashValue",
                        "value": "4412.25",
                        "currency": "USD",
                    }
                ]
            )

        with self.assertRaisesRegex(BrokerError, "one USD account balance"):
            _available_cash_notional(
                [
                    {
                        "account": account,
                        "tag": tag,
                        "value": "4412.25",
                        "currency": "USD",
                    }
                    for account in ("U123", "U456")
                    for tag in ("TotalCashValue", "AvailableFunds")
                ]
            )

    def test_tradable_capital_snapshot_uses_configured_capital_without_account_details(self) -> None:
        now = datetime(2026, 7, 17, 12, 1, tzinfo=NEW_YORK)
        with TemporaryDirectory() as temporary:
            settings = Settings(state_dir=temporary, entry_cash_reserve_usd=10)
            available, summary = _tradable_capital_snapshot(settings, now)

        self.assertEqual(10000.0, available)
        self.assertEqual("configured", summary["status"])
        self.assertEqual(10000.0, summary["usable_cash"])
        self.assertEqual(10, summary["cash_reserve_usd"])
        self.assertFalse(summary["uses_margin_buying_power"])
        self.assertEqual("configured_cap", summary["source"])
        self.assertNotIn("account", summary)

    def test_tradable_capital_snapshot_ignores_cache_values(self) -> None:
        now = datetime(2026, 7, 17, 12, 1, tzinfo=NEW_YORK)
        with TemporaryDirectory() as temporary:
            settings = Settings(
                state_dir=temporary,
                live_tradable_capital_usd=10000,
                entry_cash_reserve_usd=10,
            )
            write_market_context_cache(
                _live_context_cache_path(settings),
                session_date=now.date(),
                session=None,
                bars_by_symbol={},
                source="SMART",
                bar_size="5 mins",
                tradable_capital_usd=4388.50,
                generated_at=now,
            )
            available, summary = _tradable_capital_snapshot(settings, now)

        self.assertEqual(10000, available)
        self.assertEqual("configured", summary["status"])
        self.assertEqual(10000, summary["usable_cash"])
        self.assertEqual("configured_cap", summary["source"])

    def test_tradable_capital_snapshot_rejects_invalid_cash_reserve(self) -> None:
        now = datetime(2026, 7, 17, 12, 1, tzinfo=NEW_YORK)
        with TemporaryDirectory() as temporary:
            settings = Settings(
                state_dir=temporary,
                entry_cash_reserve_usd=-1,
            )
            with self.assertRaisesRegex(BrokerError, "must be finite and non-negative"):
                _tradable_capital_snapshot(settings, now)

    def test_cache_daemons_require_readonly_dry_run_and_no_live_permission(self) -> None:
        runners = (_run_live_quote_cache, _run_live_context_cache)
        for runner in runners:
            with self.subTest(runner=runner.__name__, gate="readonly_dry_run"):
                with self.assertRaisesRegex(BrokerError, "requires"):
                    runner(
                        Settings(readonly=False, dry_run=False),
                        SimpleNamespace(),
                    )
            with self.subTest(runner=runner.__name__, gate="live_permission"):
                with self.assertRaisesRegex(BrokerError, "ALLOW_LIVE_TRADING=false"):
                    runner(
                        Settings(
                            readonly=True,
                            dry_run=True,
                            allow_live_trading=True,
                        ),
                        SimpleNamespace(),
                    )

    def test_intraday_market_data_uses_complete_fresh_bar_cache(self) -> None:
        now = datetime(2026, 7, 15, 12, 1, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            datetime(2026, 7, 15, 9, 30, tzinfo=NEW_YORK),
            datetime(2026, 7, 15, 16, 0, tzinfo=NEW_YORK),
        )
        symbols = ("QQQ", "SOXL", "SOXS")
        bars = {
            symbol: [
                Bar(
                    datetime(2026, 7, 15, 11, 55, tzinfo=NEW_YORK),
                    10,
                    10.2,
                    9.9,
                    10.1,
                    100,
                )
            ]
            for symbol in symbols
        }
        broker = ExchangeBroker()
        with TemporaryDirectory() as temporary:
            settings = Settings(
                trading_mode="live",
                state_dir=temporary,
                live_context_cache_max_age_seconds=420,
            )
            write_market_context_cache(
                _live_context_cache_path(settings),
                session_date=now.date(),
                session=session,
                bars_by_symbol=bars,
                source="SMART",
                bar_size="5 mins",
                generated_at=now.astimezone(timezone.utc),
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(
                    ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
                ),
                settings,
            )

            exchange, loaded, _ = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

        self.assertEqual("SMART", exchange)
        self.assertEqual(bars, loaded)
        self.assertEqual([], broker.bar_calls)

    def test_intraday_market_data_refetches_cache_missing_latest_bar(self) -> None:
        now = datetime(2026, 7, 15, 12, 1, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            datetime(2026, 7, 15, 9, 30, tzinfo=NEW_YORK),
            datetime(2026, 7, 15, 16, 0, tzinfo=NEW_YORK),
        )
        symbols = ("QQQ", "SOXL", "SOXS")
        stale_bars = {
            symbol: [
                Bar(
                    datetime(2026, 7, 15, 11, 50, tzinfo=NEW_YORK),
                    10,
                    10.2,
                    9.9,
                    10.1,
                    100,
                )
            ]
            for symbol in symbols
        }
        broker = ExchangeBroker()
        with TemporaryDirectory() as temporary:
            settings = Settings(trading_mode="live", state_dir=temporary)
            write_market_context_cache(
                _live_context_cache_path(settings),
                session_date=now.date(),
                session=session,
                bars_by_symbol=stale_bars,
                source="SMART",
                bar_size="5 mins",
                generated_at=now.astimezone(timezone.utc),
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(
                    ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
                ),
                settings,
            )

            exchange, loaded, _ = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

        self.assertEqual("SMART", exchange)
        self.assertEqual(
            {("SMART", "QQQ"), ("SMART", "SOXL"), ("SMART", "SOXS")},
            set(broker.bar_calls),
        )
        self.assertEqual(
            datetime(2026, 7, 15, 11, 55, tzinfo=NEW_YORK),
            loaded["QQQ"][-1].time,
        )

    def test_intraday_market_data_allows_publication_grace_at_bar_boundary(
        self,
    ) -> None:
        now = datetime(2026, 7, 15, 12, 0, 1, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            datetime(2026, 7, 15, 9, 30, tzinfo=NEW_YORK),
            datetime(2026, 7, 15, 16, 0, tzinfo=NEW_YORK),
        )
        symbols = ("QQQ", "SOXL", "SOXS")
        bars = {
            symbol: [
                Bar(
                    datetime(2026, 7, 15, 11, 50, tzinfo=NEW_YORK),
                    10,
                    10.2,
                    9.9,
                    10.1,
                    100,
                )
            ]
            for symbol in symbols
        }
        broker = ExchangeBroker()
        with TemporaryDirectory() as temporary:
            settings = Settings(trading_mode="live", state_dir=temporary)
            write_market_context_cache(
                _live_context_cache_path(settings),
                session_date=now.date(),
                session=session,
                bars_by_symbol=bars,
                source="SMART",
                bar_size="5 mins",
                generated_at=now.astimezone(timezone.utc),
            )
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(
                    ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
                ),
                settings,
            )

            _, loaded, _ = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

        self.assertEqual(bars, loaded)
        self.assertEqual([], broker.bar_calls)

    def test_intraday_market_data_fails_closed_if_broker_is_also_behind(
        self,
    ) -> None:
        class BehindBroker(ExchangeBroker):
            def historical_bars(
                self,
                symbol: str,
                duration: str = "1 D",
                bar_size: str = "1 min",
                what_to_show: str = "TRADES",
                exchange: str = "SMART",
            ) -> list[Bar]:
                self.bar_calls.append((exchange, symbol))
                return [
                    Bar(
                        datetime(2026, 7, 15, 11, 50, tzinfo=NEW_YORK),
                        10,
                        10.2,
                        9.9,
                        10.1,
                        100,
                    )
                ]

        now = datetime(2026, 7, 15, 12, 1, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            datetime(2026, 7, 15, 9, 30, tzinfo=NEW_YORK),
            datetime(2026, 7, 15, 16, 0, tzinfo=NEW_YORK),
        )
        with TemporaryDirectory() as temporary:
            settings = Settings(trading_mode="live", state_dir=temporary)
            strategy = _build_momentum_strategy(
                _build_parser().parse_args(
                    ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
                ),
                settings,
            )

            with self.assertRaisesRegex(BrokerError, "latest completed bar missing"):
                _load_intraday_market_data(
                    BehindBroker(), settings, strategy, session, now
                )

    def test_benchmark_quote_summary_exposes_qqq_without_order_action(self) -> None:
        now = datetime(2026, 7, 16, 14, 0, 1, tzinfo=timezone.utc)
        quote = Quote(
            "QQQ",
            bid=712.4,
            ask=712.5,
            last=712.45,
            close=710.0,
            market_time="2026-07-16T14:00:00+00:00",
            observed_at="2026-07-16T14:00:00.500000+00:00",
        )

        summary = _benchmark_quote_summary("QQQ", quote, "SMART", now)

        self.assertEqual("benchmark", summary["role"])
        self.assertEqual("QQQ", summary["symbol"])
        self.assertEqual(712.45, summary["latest_trade_price"])
        self.assertTrue(summary["latest_trade_price_available"])
        self.assertEqual(500.0, summary["quote_age_ms"])
        self.assertNotIn("action", summary)

    def test_latest_trade_price_does_not_mislabel_quote_fallback(self) -> None:
        fields = _latest_trade_price_fields(
            Quote("QQQ", bid=10.0, ask=10.2, last=None, close=9.9)
        )

        self.assertIsNone(fields["latest_trade_price"])
        self.assertFalse(fields["latest_trade_price_available"])

    def test_protective_order_display_reports_active_prices(self) -> None:
        now = datetime(2026, 7, 16, 12, 0, tzinfo=NEW_YORK)
        prefix = f"momentum-{now.date()}-SOXL-protect"
        stop = SimpleNamespace(
            order=SimpleNamespace(
                orderRef=f"{prefix}-stop",
                orderType="STP",
                auxPrice=98.5,
                lmtPrice=0,
            )
        )
        take = SimpleNamespace(
            order=SimpleNamespace(
                orderRef=f"{prefix}-take",
                orderType="LMT",
                auxPrice=0,
                lmtPrice=103.75,
            )
        )

        class ProtectionBroker:
            def active_trades_for(self, symbol, action):
                return [stop, take]

            def protective_oca_is_complete(self, *args, **kwargs):
                return True

        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        bars = [
            Bar(now - timedelta(minutes=5), 100, 101, 99, 100, 100)
            for _ in range(30)
        ]

        display = _protective_order_display(
            ProtectionBroker(),
            strategy,
            "SOXL",
            {"position": "5", "avgCost": "100"},
            bars,
            now,
        )

        self.assertEqual("holding", display["position_status"])
        self.assertEqual(0.006, display["stop_loss_pct"])
        self.assertEqual(0.0375, display["take_profit_pct"])
        self.assertEqual(98.5, display["active_stop_price"])
        self.assertEqual(103.75, display["active_take_price"])
        self.assertEqual("complete", display["protection_status"])

    def test_quote_timing_fields_include_market_time_and_age(self) -> None:
        observed = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
        quote = Quote(
            "QQQ",
            bid=10.0,
            ask=10.1,
            last=10.05,
            close=10.0,
            market_time="2026-07-16T13:59:59.500000+00:00",
            received_at="2026-07-16T14:00:00+00:00",
            observed_at=observed.isoformat(),
            published_at="2026-07-16T14:00:00.500000+00:00",
        )

        fields = _quote_timing_fields(
            quote, observed + timedelta(seconds=1.25)
        )

        self.assertEqual(1250.0, fields["quote_age_ms"])
        self.assertEqual(quote.market_time, fields["quote_market_time"])
        self.assertEqual(quote.published_at, fields["quote_published_at"])

    def test_backtest_commission_matches_live_calibration(self) -> None:
        args = _build_parser().parse_args(["backtest-momentum"])

        self.assertEqual(1.0, args.commission_per_order)

    def test_backtest_core_parameters_report_surfaces_live_aligned_fields(self) -> None:
        args = _build_parser().parse_args(
            ["backtest-momentum", "--profile", "rotation-hysteresis-v2"]
        )
        settings = Settings(
            max_order_notional=4000,
            max_risk_per_trade=300,
            entry_cash_reserve_usd=10,
            live_tradable_capital_cache_max_age_seconds=90,
            max_daily_entries=1,
        )
        strategy = _build_momentum_strategy(args, settings)

        report = _backtest_core_parameters_report(
            args,
            settings,
            strategy,
            _resolve_backtest_entry_fill_model(
                args.entry_fill_model, args.profile
            ),
        )

        self.assertEqual("rotation-hysteresis-v2", report["profile"])
        self.assertEqual("worst-case", report["resolved_entry_fill_model"])
        self.assertEqual("profile-default", report["requested_entry_fill_model"])
        self.assertEqual(4000, report["resolved_max_notional"])
        self.assertEqual(300, report["resolved_max_risk_per_trade"])
        self.assertEqual(10, report["entry_cash_reserve_usd"])
        self.assertEqual(90, report["live_tradable_capital_cache_max_age_seconds"])
        self.assertEqual(1, report["max_daily_entries"])
        self.assertEqual(4000, strategy.max_notional)
        self.assertEqual(300, strategy.max_risk_per_trade)

    def test_backtest_profile_default_fill_mode_is_pessimistic(self) -> None:
        self.assertEqual(
            "worst-case",
            _resolve_backtest_entry_fill_model(
                "profile-default", ROTATION_HYSTERESIS_V2_VERSION
            ),
        )
        self.assertEqual(
            "next-bar-open",
            _resolve_backtest_entry_fill_model("profile-default", "balanced"),
        )

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
            args, Settings(max_order_notional=4000, max_risk_per_trade=300)
        )

        self.assertEqual("rotation-hysteresis-v1", FROZEN_ROTATION_HYSTERESIS_VERSION)
        for name, expected in FROZEN_ROTATION_HYSTERESIS_PARAMETERS.items():
            self.assertEqual(expected, getattr(strategy, name), name)
        self.assertEqual(4000, strategy.max_notional)
        self.assertEqual(300, strategy.max_risk_per_trade)
        self.assertIsNone(strategy.profit_lock_activation_pct)

    def test_v2_profile_adds_frozen_profit_lock_and_entry_cutoff(self) -> None:
        args = _build_parser().parse_args(
            ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
        )
        strategy = _build_momentum_strategy(args, Settings())

        self.assertEqual("rotation-hysteresis-v2", ROTATION_HYSTERESIS_V2_VERSION)
        for name, expected in ROTATION_HYSTERESIS_V2_PARAMETERS.items():
            self.assertEqual(expected, getattr(strategy, name), name)

    def test_v3_and_v4_candidates_are_explicit_and_keep_v2_as_default(self) -> None:
        default_args = _build_parser().parse_args(["intraday-momentum"])
        v3 = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v3"]
            ),
            Settings(),
        )
        v4 = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v4"]
            ),
            Settings(),
        )

        self.assertEqual("rotation-hysteresis-v2", default_args.profile)
        self.assertEqual("rotation-hysteresis-v3", ROTATION_HYSTERESIS_V3_VERSION)
        self.assertEqual("rotation-hysteresis-v4", ROTATION_HYSTERESIS_V4_VERSION)
        for name, expected in ROTATION_HYSTERESIS_V3_PARAMETERS.items():
            self.assertEqual(expected, getattr(v3, name), name)
        for name, expected in ROTATION_HYSTERESIS_V4_PARAMETERS.items():
            self.assertEqual(expected, getattr(v4, name), name)
        self.assertFalse(v3.use_exit_hysteresis)
        self.assertEqual(0, v3.entry_momentum_lookback_bars)
        self.assertFalse(v4.use_exit_hysteresis)
        self.assertEqual(2, v4.entry_momentum_lookback_bars)

    def test_range_gated_candidate_is_isolated_from_v2(self) -> None:
        candidate = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-range-gated-v1"]
            ),
            Settings(),
        )
        baseline = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )

        self.assertEqual("rotation-range-gated-v1", ROTATION_RANGE_GATED_V1_VERSION)
        for name, expected in ROTATION_RANGE_GATED_V1_PARAMETERS.items():
            self.assertEqual(expected, getattr(candidate, name), name)
        self.assertEqual(0.0, baseline.benchmark_min_intraday_range)

    def test_insufficient_bars_still_report_available_fast_slow_diagnostics(self) -> None:
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        bars = [
            Bar(
                time=datetime(2026, 7, 16, 9, 30, tzinfo=NEW_YORK)
                + timedelta(minutes=5 * index),
                open=100 + index,
                high=101 + index,
                low=99 + index,
                close=100 + index,
                volume=100,
            )
            for index in range(21)
        ]

        decision = strategy.decide(
            "SOXL",
            Quote("SOXL", bid=120, ask=121, last=120.5, close=119),
            bars,
            benchmark_bars=bars,
        )

        self.assertEqual("need at least 30 bars", decision.reason)
        self.assertIn("fast_ema", decision.meta)
        self.assertIn("slow_ema", decision.meta)

    def test_mandatory_flatten_does_not_require_signal_market_data(self) -> None:
        class FlattenBroker:
            def __init__(self):
                self.placed = []

            def positions(self):
                return [
                    {
                        "symbol": "SOXL",
                        "position": "5",
                        "avgCost": "100",
                    }
                ]

            def active_trades_for(self, symbol, action):
                return []

            def active_order_quantity(self, symbol, action):
                return 0.0

            def place_order(self, request):
                self.placed.append(request)
                return SimpleNamespace()

        broker = FlattenBroker()
        settings = Settings(readonly=False, dry_run=False, trading_mode="paper")
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            settings,
        )
        now = datetime(2026, 7, 16, 15, 50, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            now.replace(hour=9, minute=30),
            now.replace(hour=16, minute=0),
        )

        handled = _flatten_strategy_positions_if_due(
            broker, settings, strategy, now, session
        )

        self.assertTrue(handled)
        self.assertEqual(1, len(broker.placed))
        self.assertEqual("SELL", broker.placed[0].action)
        self.assertTrue(broker.placed[0].reduce_only)

    def test_orphaned_entry_buy_is_cancelled_before_next_run(self) -> None:
        trade = SimpleNamespace(
            contract=SimpleNamespace(symbol="SOXL"),
            order=SimpleNamespace(
                action="BUY",
                totalQuantity=5,
                orderType="LMT",
                lmtPrice=100.0,
                tif="DAY",
                orderRef="momentum-2026-07-16-SOXL-entry-120000",
            ),
            orderStatus=SimpleNamespace(
                status="Submitted", filled=2, remaining=3
            ),
            fills=[],
            log=[],
        )

        class EntryBroker:
            def __init__(self):
                self.cancelled = []

            def active_trades_for(self, symbol, action):
                if (
                    symbol == "SOXL"
                    and action == "BUY"
                    and trade.orderStatus.remaining > 0
                ):
                    return [trade]
                return []

            def cancel_order(self, active_trade):
                active_trade.orderStatus.status = "Cancelled"
                active_trade.orderStatus.remaining = 0
                self.cancelled.append(active_trade)

        broker = EntryBroker()
        now = datetime(2026, 7, 16, 12, 1, tzinfo=NEW_YORK)
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        with TemporaryDirectory() as tmpdir:
            cancelled = _cancel_orphaned_strategy_entry_orders(
                broker,
                Settings(
                    state_dir=tmpdir,
                    readonly=False,
                    dry_run=False,
                ),
                strategy,
                now,
            )

        self.assertEqual(1, cancelled)
        self.assertEqual([trade], broker.cancelled)

    def test_unresolved_orphaned_entry_buy_fails_closed(self) -> None:
        trade = SimpleNamespace(
            contract=SimpleNamespace(symbol="SOXL"),
            order=SimpleNamespace(
                action="BUY",
                totalQuantity=5,
                orderType="LMT",
                lmtPrice=100.0,
                tif="DAY",
                orderRef="momentum-2026-07-16-SOXL-entry-120000",
            ),
            orderStatus=SimpleNamespace(
                status="PendingCancel", filled=2, remaining=3
            ),
            fills=[],
            log=[],
        )

        class EntryBroker:
            def active_trades_for(self, symbol, action):
                return [trade] if symbol == "SOXL" and action == "BUY" else []

            def cancel_order(self, active_trade):
                return active_trade

        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        with TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(BrokerError, "cancellation unresolved"):
                _cancel_orphaned_strategy_entry_orders(
                    EntryBroker(),
                    Settings(
                        state_dir=tmpdir,
                        readonly=False,
                        dry_run=False,
                    ),
                    strategy,
                    datetime(2026, 7, 16, 12, 1, tzinfo=NEW_YORK),
                )

    def test_flatten_window_cancels_orphaned_buy_even_without_position(self) -> None:
        trade = SimpleNamespace(
            contract=SimpleNamespace(symbol="SOXL"),
            order=SimpleNamespace(
                action="BUY",
                totalQuantity=5,
                orderType="LMT",
                lmtPrice=100.0,
                tif="DAY",
                orderRef="momentum-2026-07-16-SOXL-entry-154900",
            ),
            orderStatus=SimpleNamespace(
                status="Submitted", filled=0, remaining=5
            ),
            fills=[],
            log=[],
        )

        class FlattenBroker:
            def __init__(self):
                self.cancelled = []

            def active_trades_for(self, symbol, action):
                if action == "BUY" and trade.orderStatus.remaining > 0:
                    return [trade]
                return []

            def cancel_order(self, active_trade):
                active_trade.orderStatus.status = "Cancelled"
                active_trade.orderStatus.remaining = 0
                self.cancelled.append(active_trade)

            def positions(self):
                return []

        now = datetime(2026, 7, 16, 15, 50, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            now.replace(hour=9, minute=30),
            now.replace(hour=16, minute=0),
        )
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        broker = FlattenBroker()
        with TemporaryDirectory() as tmpdir:
            handled = _flatten_strategy_positions_if_due(
                broker,
                Settings(
                    state_dir=tmpdir,
                    readonly=False,
                    dry_run=False,
                ),
                strategy,
                now,
                session,
            )

        self.assertTrue(handled)
        self.assertEqual([trade], broker.cancelled)

    def test_mandatory_flatten_does_not_cancel_or_duplicate_eod_sell(self) -> None:
        existing = SimpleNamespace(
            order=SimpleNamespace(
                orderRef="momentum-2026-07-16-SOXL-eod-exit",
                action="SELL",
            ),
            orderStatus=SimpleNamespace(
                status="Submitted",
                filled=0,
                remaining=5,
            ),
        )

        class FlattenBroker:
            def __init__(self):
                self.cancelled = []
                self.placed = []

            def positions(self):
                return [
                    {
                        "symbol": "SOXL",
                        "position": "5",
                        "avgCost": "100",
                    }
                ]

            def active_trades_for(self, symbol, action):
                return [existing]

            def cancel_order(self, trade):
                self.cancelled.append(trade)

            def active_order_quantity(self, symbol, action):
                return 5.0

            def place_order(self, request):
                self.placed.append(request)
                return SimpleNamespace()

        broker = FlattenBroker()
        settings = Settings(readonly=False, dry_run=False, trading_mode="paper")
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            settings,
        )
        now = datetime(2026, 7, 16, 15, 50, tzinfo=NEW_YORK)
        session = MarketSession(
            now.date(),
            now.replace(hour=9, minute=30),
            now.replace(hour=16, minute=0),
        )

        handled = _flatten_strategy_positions_if_due(
            broker, settings, strategy, now, session
        )

        self.assertTrue(handled)
        self.assertEqual([], broker.cancelled)
        self.assertEqual([], broker.placed)

    def test_incomplete_protective_oca_is_cancelled_and_rebuilt(self) -> None:
        def trade(order_ref, order_type, remaining=5):
            return SimpleNamespace(
                order=SimpleNamespace(
                    orderRef=order_ref,
                    orderType=order_type,
                    totalQuantity=5,
                    action="SELL",
                    tif="GTC",
                    lmtPrice=110 if order_type == "LMT" else None,
                ),
                orderStatus=SimpleNamespace(
                    status="Submitted",
                    filled=0,
                    remaining=remaining,
                ),
                fills=[],
                log=[],
            )

        class ProtectionBroker:
            def __init__(self, existing):
                self.existing = existing
                self.cancelled = []
                self.created = []

            def protective_oca_is_complete(self, *args, **kwargs):
                return False

            def active_trades_for(self, symbol, action):
                return [
                    item
                    for item in self.existing
                    if float(item.orderStatus.remaining) > 0
                ]

            def cancel_order(self, item):
                item.orderStatus.status = "Cancelled"
                item.orderStatus.remaining = 0
                self.cancelled.append(item)

            def active_order_quantity(self, symbol, action):
                return sum(
                    float(item.orderStatus.remaining) for item in self.existing
                )

            def place_protective_oca(
                self, symbol, quantity, stop_price, take_price, *, order_ref
            ):
                created = (
                    trade(f"{order_ref}-stop", "STP"),
                    trade(f"{order_ref}-take", "LMT"),
                )
                self.created.append(created)
                return created

        now = datetime(2026, 7, 16, 12, 0, tzinfo=NEW_YORK)
        prefix = f"momentum-{now.date()}-SOXL-protect"
        broker = ProtectionBroker([trade(f"{prefix}-stop", "STP")])
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        bars = [
            Bar(
                time=now - timedelta(minutes=5 * (30 - index)),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=100,
            )
            for index in range(30)
        ]
        with TemporaryDirectory() as tmpdir:
            status = _ensure_protective_oca(
                broker,
                Settings(state_dir=tmpdir),
                strategy,
                "SOXL",
                {"position": "5", "avgCost": "100"},
                bars,
                now,
            )

        self.assertEqual("recreated", status)
        self.assertEqual(1, len(broker.cancelled))
        self.assertEqual(1, len(broker.created))

    def test_missing_protection_is_rebuilt_from_entry_state_without_market_data(
        self,
    ) -> None:
        def protective_trade(order_ref, order_type, price):
            return SimpleNamespace(
                order=SimpleNamespace(
                    orderRef=order_ref,
                    orderType=order_type,
                    totalQuantity=5,
                    action="SELL",
                    tif="GTC",
                    lmtPrice=price if order_type == "LMT" else None,
                    auxPrice=price if order_type == "STP" else None,
                ),
                orderStatus=SimpleNamespace(
                    status="Submitted", filled=0, remaining=5
                ),
                fills=[],
                log=[],
            )

        class ProtectionBroker:
            def __init__(self):
                self.created = []

            def protective_oca_is_complete(self, *args, **kwargs):
                return False

            def active_trades_for(self, symbol, action):
                return []

            def active_order_quantity(self, symbol, action):
                return 0.0

            def place_protective_oca(
                self, symbol, quantity, stop_price, take_price, *, order_ref
            ):
                self.created.append((stop_price, take_price))
                return (
                    protective_trade(f"{order_ref}-stop", "STP", stop_price),
                    protective_trade(f"{order_ref}-take", "LMT", take_price),
                )

        now = datetime(2026, 7, 16, 12, 1, tzinfo=NEW_YORK)
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )
        request = TradeRequest(
            symbol="SOXL", action="BUY", quantity=5, order_ref="entry"
        )
        broker = ProtectionBroker()
        with TemporaryDirectory() as tmpdir:
            settings = Settings(
                state_dir=tmpdir,
                readonly=False,
                dry_run=False,
            )
            _record_daily_entry(
                settings,
                request,
                now=now,
                filled_quantity=5,
                average_fill_price=100,
                protective_stop_price=97.5,
                protective_take_price=104.25,
            )
            self.assertEqual(
                (97.5, 104.25),
                _latest_entry_protective_prices(settings, "SOXL", now),
            )

            _ensure_positions_protected_before_market_data(
                broker,
                settings,
                strategy,
                {"SOXL": {"position": "5", "avgCost": "100"}},
                now,
            )

        self.assertEqual([(97.5, 104.25)], broker.created)

    def test_incomplete_protection_does_not_cancel_unrelated_sell(self) -> None:
        unrelated = SimpleNamespace(
            order=SimpleNamespace(
                orderRef="manual-exit",
                orderType="LMT",
                totalQuantity=5,
                action="SELL",
            ),
            orderStatus=SimpleNamespace(
                status="Submitted",
                filled=0,
                remaining=5,
            ),
        )

        class ProtectionBroker:
            def __init__(self):
                self.cancelled = []

            def protective_oca_is_complete(self, *args, **kwargs):
                return False

            def active_trades_for(self, symbol, action):
                return [unrelated]

            def cancel_order(self, trade):
                self.cancelled.append(trade)

        now = datetime(2026, 7, 16, 12, 0, tzinfo=NEW_YORK)
        broker = ProtectionBroker()
        strategy = _build_momentum_strategy(
            _build_parser().parse_args(
                ["intraday-momentum", "--profile", "rotation-hysteresis-v2"]
            ),
            Settings(),
        )

        with self.assertRaisesRegex(BrokerError, "non-protective SELL"):
            _ensure_protective_oca(
                broker,
                Settings(),
                strategy,
                "SOXL",
                {"position": "5", "avgCost": "100"},
                [],
                now,
            )

        self.assertEqual([], broker.cancelled)

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

    def test_backtest_capital_defaults_to_live_budget(self) -> None:
        args = _build_parser().parse_args(["backtest-momentum"])

        self.assertEqual(10000.0, args.capital)

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

    def test_completed_bar_freshness_uses_bar_end_time(self) -> None:
        now = datetime(2026, 7, 17, 9, 44, 12, tzinfo=NEW_YORK)
        recently_completed = Bar(
            time=datetime(2026, 7, 17, 9, 35, tzinfo=NEW_YORK),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        broker = FakeBroker([recently_completed])

        bars = _fresh_historical_bars(
            broker,
            Settings(trading_mode="live", live_bar_max_age_seconds=420),
            "QQQ",
            bar_size="5 mins",
            completed_only=True,
            now=now,
        )

        self.assertEqual([recently_completed], bars)

    def test_completed_bar_still_rejects_stale_completion_time(self) -> None:
        now = datetime(2026, 7, 17, 9, 47, 1, tzinfo=NEW_YORK)
        stale = Bar(
            time=datetime(2026, 7, 17, 9, 35, tzinfo=NEW_YORK),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        broker = FakeBroker([stale])

        with self.assertRaisesRegex(BrokerError, "stale"):
            _fresh_historical_bars(
                broker,
                Settings(trading_mode="live", live_bar_max_age_seconds=420),
                "QQQ",
                bar_size="5 mins",
                completed_only=True,
                now=now,
            )

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
                [(("QQQ", "SOXL", "SOXS"), "SMART")],
                broker.quote_group_calls,
            )

    def test_intraday_market_data_prefers_fresh_quote_cache(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = Settings(trading_mode="live", state_dir=tmpdir)
            symbols = ("QQQ", "SOXL", "SOXS")
            writer = QuoteCacheWriter(
                Path(tmpdir) / "live-quotes.json", symbols
            )
            writer.update(
                {
                    symbol: Quote(symbol, bid=10.0, ask=10.1, last=10.05, close=10.0)
                    for symbol in symbols
                },
                force=True,
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

            _, _, quotes = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )

            self.assertEqual(set(symbols), set(quotes))
            self.assertEqual([], broker.quote_group_calls)

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
                protective_stop_price=99.5,
                protective_take_price=105.05,
            )

            path = next(Path(tmpdir).glob("entries-*.json"))
            row = loads(path.read_text())["entries"][0]
            self.assertEqual(3.0, row["filled_quantity"])
            self.assertEqual(101.25, row["average_fill_price"])
            self.assertEqual("rotation-hysteresis-v2", row["strategy_version"])
            self.assertEqual(99.5, row["protective_stop_price"])
            self.assertEqual(105.05, row["protective_take_price"])
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
