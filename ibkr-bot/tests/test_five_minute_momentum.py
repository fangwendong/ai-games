from ibkr_bot.models import PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.five_minute_momentum import FiveMinuteMomentumStrategy


def bars(values: list[float], volumes: list[float] | None = None) -> list[Bar]:
    volumes = volumes or [5_000_000 for _ in values]
    return [
        Bar(timestamp=str(index), close=value, volume=volumes[index])
        for index, value in enumerate(values)
    ]


def bullish_series(length: int = 30) -> list[float]:
    return [100 + index * 0.4 for index in range(length)]


def bearish_series(length: int = 30) -> list[float]:
    return [112 - index * 0.4 for index in range(length)]


def test_generates_buy_on_intraday_bullish_structure() -> None:
    strategy = FiveMinuteMomentumStrategy(fast_window=6, slow_window=24, volume_window=12)
    volumes = [4_000_000 for _ in range(29)] + [8_000_000]

    intent = strategy.generate("SPY", bars(bullish_series(), volumes))

    assert intent is not None
    assert intent.side == Side.BUY
    assert intent.quantity == 1


def test_generates_sell_when_intraday_structure_breaks() -> None:
    strategy = FiveMinuteMomentumStrategy(fast_window=6, slow_window=24, volume_window=12)
    position = PositionSnapshot(symbol="SPY", quantity=2, market_price=100)
    volumes = [4_000_000 for _ in range(29)] + [8_000_000]

    intent = strategy.generate("SPY", bars(bearish_series(), volumes), position)

    assert intent is not None
    assert intent.side == Side.SELL
    assert intent.quantity == 2


def test_score_reports_intraday_signal_direction() -> None:
    strategy = FiveMinuteMomentumStrategy(fast_window=3, slow_window=8, volume_window=4)
    volumes = [4_000_000 for _ in range(29)] + [8_000_000]

    bullish = strategy.score("VOO", bars(bullish_series(), volumes))
    bearish = strategy.score("XLE", bars(bearish_series(), volumes))

    assert bullish is not None
    assert bearish is not None
    assert bullish.signal == "BUY"
    assert bearish.signal == "SELL"
    assert bullish.score > bearish.score
