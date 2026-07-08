from ibkr_bot.models import PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.short_term_momentum_rotation import ShortTermMomentumRotationStrategy


def bars(values: list[float]) -> list[Bar]:
    return [Bar(timestamp=str(index), close=value, volume=5_000_000) for index, value in enumerate(values)]


def rising_series(length: int = 80) -> list[float]:
    return [100 + index * 1.0 for index in range(length)]


def flat_series(length: int = 80) -> list[float]:
    return [100 for _ in range(length)]


def noisy_series(length: int = 80) -> list[float]:
    values: list[float] = []
    for index in range(length):
        swing = 2.0 if index % 2 == 0 else -2.0
        values.append(100 + swing)
    return values


def test_prefers_stronger_short_term_momentum() -> None:
    strategy = ShortTermMomentumRotationStrategy(lookback=30, volatility_window=10, volume_window=10)
    strong = strategy.score("QQQ", bars(rising_series()))
    weak = strategy.score("SPY", bars(noisy_series()))

    assert strong is not None
    assert weak is not None
    assert strong.score > weak.score


def test_build_plan_buys_top_symbol_and_exits_other_positions() -> None:
    strategy = ShortTermMomentumRotationStrategy(lookback=30, volatility_window=10, volume_window=10)
    universe = {
        "QQQ": bars(rising_series()),
        "SPY": bars(flat_series()),
    }
    positions = {
        "SPY": PositionSnapshot(symbol="SPY", quantity=2, market_price=100),
    }

    plan = strategy.build_plan(universe, positions)

    assert plan.selected_symbol == "QQQ"
    assert any(order.contract.symbol == "SPY" and order.side == Side.SELL for order in plan.orders)
    assert any(order.contract.symbol == "QQQ" and order.side == Side.BUY for order in plan.orders)
