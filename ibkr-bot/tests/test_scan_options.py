from types import SimpleNamespace

from pathlib import Path

from ibkr_bot.config import Settings
from ibkr_bot.main import _resolve_rotation_symbols, _resolve_scan_options, _resolve_scan_symbols


def test_five_minute_scan_defaults_to_5m_bars() -> None:
    options = _resolve_scan_options(
        SimpleNamespace(
            strategy="five_minute_momentum",
            duration=None,
            bar_size=None,
        )
    )

    assert options == {
        "duration": "2 D",
        "bar_size": "5 mins",
        "use_rth": True,
    }


def test_daily_scan_defaults_to_daily_bars() -> None:
    options = _resolve_scan_options(
        SimpleNamespace(
            strategy="volatility_managed_trend",
            duration=None,
            bar_size=None,
        )
    )

    assert options == {
        "duration": "30 D",
        "bar_size": "1 day",
        "use_rth": True,
    }


def test_five_minute_scan_uses_rotation_universe_by_default() -> None:
    settings = Settings(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        allow_extended_hours=False,
        symbols=("SPY", "QQQ"),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
        rotation_symbols=(),
    )
    rotation_symbols = _resolve_rotation_symbols(settings, None, "five_minute_momentum")
    symbols = _resolve_scan_symbols(settings, None, "five_minute_momentum", rotation_symbols)

    assert symbols == rotation_symbols


def test_tech_semiconductor_scan_uses_rotation_universe_by_default() -> None:
    settings = Settings(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        allow_extended_hours=False,
        symbols=("SPY", "QQQ"),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
        rotation_symbols=(),
    )
    rotation_symbols = _resolve_rotation_symbols(settings, None, "tech_semiconductor_rotation")
    symbols = _resolve_scan_symbols(settings, None, "tech_semiconductor_rotation", rotation_symbols)

    assert symbols == rotation_symbols


def test_tech_semiconductor_rotation_uses_tech_universe() -> None:
    settings = Settings(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        allow_extended_hours=False,
        symbols=("SPY", "QQQ"),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
        rotation_symbols=(),
    )

    rotation_symbols = _resolve_rotation_symbols(settings, None, "tech_semiconductor_rotation")

    assert rotation_symbols == ["QQQ", "XLK", "IYW", "SMH", "SOXX"]


def test_vwap_pullback_uses_intraday_leveraged_universe() -> None:
    settings = Settings(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        allow_extended_hours=False,
        symbols=("SPY", "QQQ"),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
        rotation_symbols=(),
    )

    rotation_symbols = _resolve_rotation_symbols(settings, None, "vwap_pullback")

    assert rotation_symbols == ["SOXL", "TQQQ", "TECL"]


def test_intraday_scans_default_to_five_minute_bars() -> None:
    opening_range = _resolve_scan_options(
        SimpleNamespace(
            strategy="opening_range_breakout",
            duration=None,
            bar_size=None,
        )
    )
    vwap_pullback = _resolve_scan_options(
        SimpleNamespace(
            strategy="vwap_pullback",
            duration=None,
            bar_size=None,
        )
    )

    assert opening_range == {
        "duration": "2 D",
        "bar_size": "5 mins",
        "use_rth": True,
    }
    assert vwap_pullback == {
        "duration": "2 D",
        "bar_size": "5 mins",
        "use_rth": True,
    }
