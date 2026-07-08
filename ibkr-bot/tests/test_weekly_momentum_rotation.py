from ibkr_bot.models import PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.weekly_momentum_rotation import WeeklyMomentumRotationStrategy


def bars(values: list[float]) -> list[Bar]:
    return [Bar(timestamp=str(index), close=value, volume=5_000_000) for index, value in enumerate(values)]


def rising_series(length: int = 80) -> list[float]:
    return [100 + index * 0.8 for index in range(length)]


def flat_series(length: int = 80) -> list[float]:
    return [100 for _ in range(length)]


def test_prefers_stronger_weekly_momentum() -> None:
    strategy = WeeklyMomentumRotationStrategy(lookback=20, volatility_window=10, volume_window=10)
    strong = strategy.score("QQQ", bars(rising_series()))
    weak = strategy.score("SPY", bars(flat_series()))

    assert strong is not None
    assert weak is not None
    assert strong.score > weak.score


def test_build_plan_buys_top_symbol_and_exits_other_positions() -> None:
    strategy = WeeklyMomentumRotationStrategy(lookback=20, volatility_window=10, volume_window=10)
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


def test_build_plan_moves_to_cash_when_market_filter_is_off() -> None:
    strategy = WeeklyMomentumRotationStrategy(lookback=20, volatility_window=10, volume_window=10, market_filter_window=5)
    universe = {
        "SPY": bars([100, 99, 98, 97, 96, 95, 94]),
        "QQQ": bars(rising_series(7)),
    }
    positions = {
        "QQQ": PositionSnapshot(symbol="QQQ", quantity=2, market_price=100),
    }

    plan = strategy.build_plan(universe, positions)

    assert plan.selected_symbol is None
    assert len(plan.orders) == 1
    assert plan.orders[0].contract.symbol == "QQQ"
    assert plan.orders[0].side == Side.SELL
