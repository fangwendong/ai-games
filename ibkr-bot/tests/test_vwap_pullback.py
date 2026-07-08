from datetime import datetime, timedelta

from ibkr_bot.models import Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.vwap_pullback import VwapPullbackStrategy
from ibkr_bot.backtest import run_intraday_signal_backtest


def bars(values: list[float], volumes: list[float] | None = None) -> list[Bar]:
    volumes = volumes or [5_000_000 for _ in values]
    start = datetime(2024, 1, 1, 9, 30)
    return [
        Bar(timestamp=(start + timedelta(minutes=5 * index)).isoformat(), close=value, volume=volumes[index])
        for index, value in enumerate(values)
    ]


def test_generates_buy_only_on_vwap_reclaim_cross() -> None:
    strategy = VwapPullbackStrategy(
        pullback_window=20,
        trend_window=30,
        volume_window=8,
        pullback_depth=0.01,
        min_volume_multiple=1.0,
        min_trend_return=-0.01,
    )
    session = [100.0] * 26 + [99.2, 98.8, 98.4, 99.1, 100.4]
    intent = strategy.generate("SOXL", bars(session))

    assert intent is not None
    assert intent.side == Side.BUY


def test_no_buy_when_price_has_not_reclaimed_vwap() -> None:
    strategy = VwapPullbackStrategy(
        pullback_window=20,
        trend_window=30,
        volume_window=8,
        pullback_depth=0.01,
        min_volume_multiple=1.0,
        min_trend_return=-0.01,
    )
    session = [100.0] * 26 + [99.2, 98.8, 98.4, 99.1, 99.4]
    intent = strategy.generate("SOXL", bars(session))

    assert intent is None


def test_intraday_backtest_exits_on_vwap_breakdown() -> None:
    strategy = VwapPullbackStrategy(
        pullback_window=20,
        trend_window=30,
        volume_window=8,
        pullback_depth=0.01,
        min_volume_multiple=1.0,
        min_trend_return=-0.01,
    )
    session = [100.0] * 26 + [99.2, 98.8, 98.4, 99.1, 100.4, 100.8, 101.2, 101.1, 101.0, 100.9, 99.4, 98.9]
    summary, _curve = run_intraday_signal_backtest(
        {"SOXL": bars(session)},
        strategy,
        starting_capital=3_000.0,
        commission_per_trade=1.0,
        slippage_bps=10.0,
    )

    assert summary.trade_count >= 2
    assert summary.ending_capital != summary.starting_capital
