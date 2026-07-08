from datetime import date, datetime, timedelta

from types import SimpleNamespace

from ibkr_bot.backtest import (
    run_five_minute_momentum_backtest,
    run_intraday_signal_backtest,
    run_quality_low_vol_rotation_backtest,
    run_trend_backtest,
)
from ibkr_bot.main import _build_backtest_strategy, _resolve_backtest_options
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.five_minute_momentum import FiveMinuteMomentumStrategy
from ibkr_bot.strategy.moving_average import MovingAverageCrossStrategy
from ibkr_bot.strategy.opening_range_breakout import OpeningRangeBreakoutStrategy
from ibkr_bot.strategy.quality_low_vol_rotation import QualityLowVolRotationStrategy
from ibkr_bot.strategy.tech_semiconductor_rotation import TechSemiconductorRotationStrategy
from ibkr_bot.strategy.volatility_managed import VolatilityManagedTrendStrategy
from ibkr_bot.strategy.vwap_pullback import VwapPullbackStrategy
from ibkr_bot.strategy.weekly_momentum_rotation import WeeklyMomentumRotationStrategy


def bars(values: list[float]) -> list[Bar]:
    start = date(2023, 1, 1)
    return [
        Bar(timestamp=(start + timedelta(days=index)).isoformat(), close=value, volume=5_000_000)
        for index, value in enumerate(values)
    ]


def smooth_series(length: int = 300) -> list[float]:
    return [100 + index * 0.15 for index in range(length)]


def noisy_series(length: int = 300) -> list[float]:
    values: list[float] = []
    for index in range(length):
        base = 100 + index * 0.02
        swing = 2.0 if index % 2 == 0 else -2.0
        values.append(base + swing)
    return values


def intraday_bars(values: list[float], start: datetime | None = None) -> list[Bar]:
    start = start or datetime(2023, 1, 1, 9, 30)
    return [
        Bar(timestamp=(start + timedelta(minutes=5 * index)).isoformat(), close=value, volume=5_000_000)
        for index, value in enumerate(values)
    ]


def test_backtest_prefers_smoother_series() -> None:
    strategy = QualityLowVolRotationStrategy(
        lookback=60,
        volatility_window=20,
        max_annualized_volatility=1.0,
        min_score=-10.0,
    )
    summary, curve = run_quality_low_vol_rotation_backtest(
        {
            "SPY": bars(smooth_series()),
            "QQQ": bars(noisy_series()),
        },
        strategy,
        starting_capital=10_000.0,
    )

    assert summary.strategy == "quality_low_vol_rotation"
    assert summary.rebalance_frequency == "monthly"
    assert summary.trade_count >= 1
    assert summary.selected_symbol_counts["SPY"] >= 1
    assert summary.total_return > 0
    assert curve[-1].equity == summary.ending_capital


def test_backtest_supports_daily_rebalance() -> None:
    strategy = QualityLowVolRotationStrategy(
        lookback=60,
        volatility_window=20,
        max_annualized_volatility=1.0,
        min_score=-10.0,
    )
    summary, _curve = run_quality_low_vol_rotation_backtest(
        {
            "SPY": bars(smooth_series()),
            "QQQ": bars(noisy_series()),
        },
        strategy,
        starting_capital=10_000.0,
        rebalance_frequency="daily",
    )

    assert summary.rebalance_frequency == "daily"
    assert summary.rebalance_count > 100
    assert summary.trade_count >= 1
    assert summary.selected_symbol_counts["SPY"] >= 1


def test_backtest_profile_defaults() -> None:
    monthly = _resolve_backtest_options(SimpleNamespace(profile="monthly", rebalance_frequency=None, lookback=None, volatility_window=None, volume_window=None))
    daily = _resolve_backtest_options(SimpleNamespace(profile="daily", rebalance_frequency=None, lookback=None, volatility_window=None, volume_window=None))
    short_term = _resolve_backtest_options(SimpleNamespace(strategy="short_term_momentum_rotation", profile=None, rebalance_frequency=None, lookback=None, volatility_window=None, volume_window=None))
    weekly = _resolve_backtest_options(SimpleNamespace(strategy="weekly_momentum_rotation", profile=None, rebalance_frequency=None, lookback=None, volatility_window=None, volume_window=None))
    tech = _resolve_backtest_options(SimpleNamespace(strategy="tech_semiconductor_rotation", profile=None, rebalance_frequency=None, lookback=None, volatility_window=None, volume_window=None))
    intraday = _resolve_backtest_options(
        SimpleNamespace(
            strategy="five_minute_momentum",
            profile=None,
            rebalance_frequency=None,
            lookback=None,
            volatility_window=None,
            volume_window=None,
            duration=None,
            bar_size=None,
        )
    )

    assert monthly == {
        "rebalance_frequency": "monthly",
        "lookback": 60,
        "trend_window": 60,
        "volatility_window": 20,
        "volume_window": 20,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.0,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }
    assert daily == {
        "rebalance_frequency": "daily",
        "lookback": 10,
        "trend_window": 10,
        "volatility_window": 5,
        "volume_window": 5,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.0,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }
    assert short_term == {
        "rebalance_frequency": "daily",
        "lookback": 30,
        "trend_window": 30,
        "volatility_window": 10,
        "volume_window": 20,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.0,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }
    assert weekly == {
        "rebalance_frequency": "weekly",
        "lookback": 20,
        "trend_window": 20,
        "volatility_window": 10,
        "volume_window": 10,
        "max_annualized_volatility": 0.30,
        "min_trailing_return": 0.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.02,
        "market_filter_symbol": "SPY",
        "market_filter_window": 50,
    }
    assert tech == {
        "rebalance_frequency": "weekly",
        "lookback": 60,
        "trend_window": 60,
        "volatility_window": 20,
        "volume_window": 20,
        "max_annualized_volatility": 0.35,
        "min_trailing_return": 0.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.03,
        "market_filter_symbol": "SPY",
        "market_filter_window": 50,
    }
    assert intraday == {
        "rebalance_frequency": "daily",
        "lookback": 3,
        "trend_window": 3,
        "volatility_window": 8,
        "volume_window": 4,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.0,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
        "duration": "2 D",
        "bar_size": "5 mins",
        "use_rth": True,
    }
    assert _resolve_backtest_options(
        SimpleNamespace(
            strategy="opening_range_breakout",
            profile=None,
            rebalance_frequency=None,
            lookback=None,
            volatility_window=None,
            volume_window=None,
            max_annualized_volatility=None,
            min_trailing_return=None,
            switch_score_margin=None,
            market_filter_symbol=None,
            market_filter_window=None,
        )
    ) == {
        "rebalance_frequency": "daily",
        "duration": "5 D",
        "bar_size": "5 mins",
        "use_rth": True,
        "lookback": 6,
        "trend_window": 6,
        "volatility_window": 8,
        "volume_window": 4,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.01,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }
    assert _resolve_backtest_options(
        SimpleNamespace(
            strategy="vwap_pullback",
            profile=None,
            rebalance_frequency=None,
            lookback=None,
            trend_window=None,
            volatility_window=None,
            volume_window=None,
            max_annualized_volatility=None,
            min_trailing_return=None,
            min_trend_return=None,
            switch_score_margin=None,
            market_filter_symbol=None,
            market_filter_window=None,
        )
    ) == {
        "rebalance_frequency": "daily",
        "duration": "5 D",
        "bar_size": "5 mins",
        "use_rth": True,
        "lookback": 12,
        "trend_window": 16,
        "volatility_window": 8,
        "volume_window": 4,
        "max_annualized_volatility": 0.20,
        "min_trailing_return": -1.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.0,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }


def test_low_turnover_profile_defaults() -> None:
    options = _resolve_backtest_options(
        SimpleNamespace(
            strategy="quality_low_vol_rotation",
            profile="low_turnover",
            rebalance_frequency=None,
            lookback=None,
            volatility_window=None,
            volume_window=None,
            max_annualized_volatility=None,
            min_trailing_return=None,
            switch_score_margin=None,
        )
    )

    assert options == {
        "rebalance_frequency": "weekly",
        "lookback": 60,
        "trend_window": 60,
        "volatility_window": 20,
        "volume_window": 20,
        "max_annualized_volatility": 0.25,
        "min_trailing_return": 0.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.03,
        "market_filter_symbol": "SPY",
        "market_filter_window": 0,
    }


def test_defensive_profile_defaults() -> None:
    options = _resolve_backtest_options(
        SimpleNamespace(
            strategy="quality_low_vol_rotation",
            profile="defensive",
            rebalance_frequency=None,
            lookback=None,
            volatility_window=None,
            volume_window=None,
            max_annualized_volatility=None,
            min_trailing_return=None,
            switch_score_margin=None,
            market_filter_symbol=None,
            market_filter_window=None,
        )
    )

    assert options == {
        "rebalance_frequency": "weekly",
        "lookback": 60,
        "trend_window": 60,
        "volatility_window": 20,
        "volume_window": 20,
        "max_annualized_volatility": 0.25,
        "min_trailing_return": 0.0,
        "min_trend_return": 0.0,
        "switch_score_margin": 0.05,
        "market_filter_symbol": "SPY",
        "market_filter_window": 200,
    }


def test_backtest_supports_weekly_rebalance() -> None:
    strategy = QualityLowVolRotationStrategy(
        lookback=20,
        volatility_window=10,
        max_annualized_volatility=1.0,
        min_score=-10.0,
    )
    summary, _curve = run_quality_low_vol_rotation_backtest(
        {
            "SPY": bars(smooth_series(120)),
            "QQQ": bars(noisy_series(120)),
        },
        strategy,
        starting_capital=10_000.0,
        rebalance_frequency="weekly",
    )

    assert summary.rebalance_frequency == "weekly"
    assert 15 <= summary.rebalance_count <= 20
    assert summary.trade_count >= 1


def test_backtest_supports_weekly_momentum_rotation() -> None:
    strategy = WeeklyMomentumRotationStrategy(
        lookback=20,
        volatility_window=10,
        volume_window=10,
        max_annualized_volatility=1.0,
        min_score=-10.0,
        market_filter_window=0,
    )
    summary, _curve = run_quality_low_vol_rotation_backtest(
        {
            "SPY": bars(smooth_series(180)),
            "QQQ": bars([100 + index * 0.35 for index in range(180)]),
            "IWM": bars([100 + index * 0.12 + (1.5 if index % 7 == 0 else 0.0) for index in range(180)]),
        },
        strategy,
        starting_capital=5_000.0,
        rebalance_frequency="weekly",
    )

    assert summary.strategy == "weekly_momentum_rotation"
    assert summary.rebalance_frequency == "weekly"
    assert summary.trade_count >= 1
    assert summary.ending_capital != summary.starting_capital


def test_backtest_supports_tech_semiconductor_rotation() -> None:
    strategy = TechSemiconductorRotationStrategy(
        lookback=20,
        volatility_window=10,
        volume_window=10,
        max_annualized_volatility=1.0,
        min_score=-10.0,
        market_filter_window=0,
    )
    summary, _curve = run_quality_low_vol_rotation_backtest(
        {
            "QQQ": bars([100 + index * 0.30 for index in range(180)]),
            "XLK": bars([100 + index * 0.15 for index in range(180)]),
            "SMH": bars([100 + index * 0.42 for index in range(180)]),
            "SOXX": bars([100 + index * 0.18 for index in range(180)]),
            "SPY": bars(smooth_series(180)),
        },
        strategy,
        starting_capital=5_000.0,
        rebalance_frequency="weekly",
    )

    assert summary.strategy == "tech_semiconductor_rotation"
    assert summary.rebalance_frequency == "weekly"
    assert summary.trade_count >= 1
    assert summary.ending_capital != summary.starting_capital


def test_backtest_supports_five_minute_momentum() -> None:
    strategy = FiveMinuteMomentumStrategy(fast_window=3, slow_window=8, volume_window=4)
    spy_series = [
        100,
        100,
        100,
        100,
        100,
        100.5,
        101.0,
        101.5,
        102.0,
        102.4,
        102.2,
        103.0,
        103.5,
    ]
    summary, curve = run_five_minute_momentum_backtest(
        {
            "SPY": intraday_bars(spy_series),
            "QQQ": intraday_bars([100 for _ in range(len(spy_series))]),
        },
        strategy,
        starting_capital=3_000.0,
    )

    assert summary.strategy == "five_minute_momentum"
    assert summary.rebalance_frequency == "5m"
    assert summary.starting_capital == 3_000.0
    assert summary.ending_capital > summary.starting_capital
    assert summary.total_return > 0
    assert summary.trade_count >= 1
    assert summary.selected_symbol_counts["SPY"] >= 1
    assert curve[-1].equity == summary.ending_capital


def test_backtest_supports_volatility_managed_trend() -> None:
    strategy = VolatilityManagedTrendStrategy(trend_window=20, volatility_window=10, max_annualized_volatility=1.0)
    summary, _curve = run_trend_backtest(
        bars(smooth_series(120)),
        strategy,
        starting_capital=3_000.0,
    )

    assert summary.strategy == "volatility_managed_trend"
    assert summary.rebalance_frequency == "trend"
    assert summary.trade_count >= 1
    assert summary.ending_capital >= summary.starting_capital


def test_backtest_supports_moving_average_cross() -> None:
    strategy = MovingAverageCrossStrategy(fast_window=5, slow_window=20)
    series = [100] * 20 + [100 + index * 0.5 for index in range(60)]
    summary, _curve = run_trend_backtest(
        bars(series),
        strategy,
        starting_capital=3_000.0,
    )

    assert summary.strategy == "moving_average_cross"
    assert summary.rebalance_frequency == "trend"
    assert summary.trade_count >= 1


def test_build_backtest_strategy_supports_intraday() -> None:
    strategy = _build_backtest_strategy(
        "five_minute_momentum",
        {
            "lookback": 3,
            "volatility_window": 8,
            "volume_window": 4,
        },
    )

    assert isinstance(strategy, FiveMinuteMomentumStrategy)
    assert strategy.fast_window == 3
    assert strategy.slow_window == 8
    assert strategy.volume_window == 4


def test_build_backtest_strategy_supports_weekly_momentum() -> None:
    strategy = _build_backtest_strategy(
        "weekly_momentum_rotation",
        {
            "lookback": 20,
            "volatility_window": 10,
            "volume_window": 10,
            "max_annualized_volatility": 0.30,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.02,
            "market_filter_symbol": "SPY",
            "market_filter_window": 50,
        },
    )

    assert isinstance(strategy, WeeklyMomentumRotationStrategy)
    assert strategy.lookback == 20
    assert strategy.market_filter_window == 50


def test_build_backtest_strategy_supports_tech_semiconductor_rotation() -> None:
    strategy = _build_backtest_strategy(
        "tech_semiconductor_rotation",
        {
            "lookback": 20,
            "volatility_window": 10,
            "volume_window": 10,
            "max_annualized_volatility": 0.35,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.03,
            "market_filter_symbol": "SPY",
            "market_filter_window": 50,
        },
    )

    assert isinstance(strategy, TechSemiconductorRotationStrategy)
    assert strategy.lookback == 20
    assert strategy.market_filter_window == 50


def test_build_backtest_strategy_supports_opening_range_breakout() -> None:
    strategy = _build_backtest_strategy(
        "opening_range_breakout",
        {
            "lookback": 6,
            "volatility_window": 8,
            "volume_window": 4,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.01,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        },
    )

    assert isinstance(strategy, OpeningRangeBreakoutStrategy)
    assert strategy.opening_range_bars == 6
    assert strategy.volume_window == 4


def test_build_backtest_strategy_supports_vwap_pullback() -> None:
    strategy = _build_backtest_strategy(
        "vwap_pullback",
        {
            "lookback": 12,
            "trend_window": 16,
            "volatility_window": 8,
            "volume_window": 4,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "min_trend_return": 0.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        },
    )

    assert isinstance(strategy, VwapPullbackStrategy)
    assert strategy.pullback_window == 12
    assert strategy.trend_window == 16
    assert strategy.volume_window == 4
    assert strategy.pullback_depth == 0.0075
    assert strategy.min_volume_multiple == 1.0
    assert strategy.stop_loss_pct == 0.015
    assert strategy.max_hold_bars == 36


def test_intraday_backtest_penalizes_commissions_and_slippage() -> None:
    strategy = FiveMinuteMomentumStrategy(fast_window=3, slow_window=8, volume_window=4)
    spy_series = [
        100,
        100,
        100,
        100,
        100,
        100.5,
        101.0,
        101.5,
        102.0,
        102.4,
        102.2,
        103.0,
        103.5,
    ]
    universe = {
        "SPY": intraday_bars(spy_series),
        "QQQ": intraday_bars([100 for _ in range(len(spy_series))]),
    }
    no_cost, _ = run_intraday_signal_backtest(universe, strategy, starting_capital=3_000.0)
    with_cost, _ = run_intraday_signal_backtest(
        universe,
        strategy,
        starting_capital=3_000.0,
        commission_per_trade=1.0,
        slippage_bps=10.0,
    )

    assert with_cost.trade_count == no_cost.trade_count
    assert with_cost.ending_capital < no_cost.ending_capital
