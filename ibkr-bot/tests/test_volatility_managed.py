from ibkr_bot.models import PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.volatility_managed import VolatilityManagedTrendStrategy


def bars(values: list[float]) -> list[Bar]:
    return [Bar(timestamp=str(index), close=value) for index, value in enumerate(values)]


def trending_up_series(length: int = 80) -> list[float]:
    return [100 + index * 0.5 for index in range(length)]


def trending_down_series(length: int = 80) -> list[float]:
    return [140 - index * 0.5 for index in range(length)]


def test_buys_when_trend_is_up_and_vol_is_low() -> None:
    strategy = VolatilityManagedTrendStrategy(trend_window=20, volatility_window=10)
    intent = strategy.generate("SPY", bars(trending_up_series()))

    assert intent is not None
    assert intent.side == Side.BUY
    assert intent.quantity == 1


def test_holds_when_already_long_and_signal_stays_positive() -> None:
    strategy = VolatilityManagedTrendStrategy(trend_window=20, volatility_window=10)
    position = PositionSnapshot(symbol="SPY", quantity=1, market_price=100)

    assert strategy.generate("SPY", bars(trending_up_series()), position) is None


def test_sells_when_trend_turns_down_while_long() -> None:
    strategy = VolatilityManagedTrendStrategy(trend_window=20, volatility_window=10)
    position = PositionSnapshot(symbol="SPY", quantity=2, market_price=100)
    intent = strategy.generate("SPY", bars(trending_down_series()), position)

    assert intent is not None
    assert intent.side == Side.SELL
    assert intent.quantity == 2

