from ibkr_bot.models import Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.moving_average import MovingAverageCrossStrategy


def bars(values: list[float]) -> list[Bar]:
    return [Bar(timestamp=str(index), close=value) for index, value in enumerate(values)]


def test_no_signal_when_history_is_short() -> None:
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=4)
    assert strategy.generate("SPY", bars([1, 2, 3])) is None


def test_generates_buy_on_bullish_cross() -> None:
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=4, quantity=3)
    intent = strategy.generate("SPY", bars([10, 10, 10, 8, 20]))
    assert intent is not None
    assert intent.side == Side.BUY
    assert intent.quantity == 3
