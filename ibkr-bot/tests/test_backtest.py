from datetime import date, timedelta

from ibkr_bot.backtest import run_quality_low_vol_rotation_backtest
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.quality_low_vol_rotation import QualityLowVolRotationStrategy


def bars(values: list[float]) -> list[Bar]:
    start = date(2023, 1, 1)
    return [Bar(timestamp=(start + timedelta(days=index)).isoformat(), close=value) for index, value in enumerate(values)]


def smooth_series(length: int = 300) -> list[float]:
    return [100 + index * 0.15 for index in range(length)]


def noisy_series(length: int = 300) -> list[float]:
    values: list[float] = []
    for index in range(length):
        base = 100 + index * 0.02
        swing = 2.0 if index % 2 == 0 else -2.0
        values.append(base + swing)
    return values


def test_backtest_prefers_smoother_series() -> None:
    strategy = QualityLowVolRotationStrategy(lookback=60, volatility_window=20, max_annualized_volatility=1.0)
    summary, curve = run_quality_low_vol_rotation_backtest(
        {
            "SPY": bars(smooth_series()),
            "QQQ": bars(noisy_series()),
        },
        strategy,
        starting_capital=10_000.0,
    )

    assert summary.strategy == "quality_low_vol_rotation"
    assert summary.trade_count >= 1
    assert summary.selected_symbol_counts["SPY"] >= 1
    assert summary.total_return > 0
    assert curve[-1].equity == summary.ending_capital
