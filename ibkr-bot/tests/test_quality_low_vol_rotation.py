from ibkr_bot.models import PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.quality_low_vol_rotation import QualityLowVolRotationStrategy


def bars(values: list[float]) -> list[Bar]:
    return [Bar(timestamp=str(index), close=value, volume=5_000_000) for index, value in enumerate(values)]


def smooth_series(length: int = 260) -> list[float]:
    return [100 + index * 0.12 for index in range(length)]


def choppy_series(length: int = 260) -> list[float]:
    values: list[float] = []
    for index in range(length):
        base = 100 + index * 0.12
        swing = 1.5 if index % 2 == 0 else -1.5
        values.append(base + swing)
    return values


def test_prefers_smoother_low_vol_series() -> None:
    strategy = QualityLowVolRotationStrategy(lookback=252, volatility_window=63, max_annualized_volatility=1.0)
    smooth = strategy.score("SPY", bars(smooth_series()))
    choppy = strategy.score("QQQ", bars(choppy_series()))

    assert smooth is not None
    assert choppy is not None
    assert smooth.score > choppy.score


def test_build_plan_selects_top_symbol_and_buys_it() -> None:
    strategy = QualityLowVolRotationStrategy(lookback=252, volatility_window=63, max_annualized_volatility=1.0)
    universe = {
        "SPY": bars(smooth_series()),
        "QQQ": bars(choppy_series()),
    }

    plan = strategy.build_plan(universe, {})

    assert plan.selected_symbol == "SPY"
    assert len(plan.orders) == 1
    assert plan.orders[0].contract.symbol == "SPY"
    assert plan.orders[0].side == Side.BUY


def test_build_plan_rotates_out_of_other_holdings() -> None:
    strategy = QualityLowVolRotationStrategy(lookback=252, volatility_window=63, max_annualized_volatility=1.0)
    universe = {
        "SPY": bars(smooth_series()),
        "QQQ": bars(choppy_series()),
    }
    positions = {
        "QQQ": PositionSnapshot(symbol="QQQ", quantity=3, market_price=101),
    }

    plan = strategy.build_plan(universe, positions)

    assert plan.selected_symbol == "SPY"
    assert len(plan.orders) == 2
    assert any(order.contract.symbol == "QQQ" and order.side == Side.SELL for order in plan.orders)
    assert any(order.contract.symbol == "SPY" and order.side == Side.BUY for order in plan.orders)


def test_build_plan_keeps_current_holding_inside_switch_margin() -> None:
    strategy = QualityLowVolRotationStrategy(
        lookback=252,
        volatility_window=63,
        max_annualized_volatility=1.0,
        switch_score_margin=10.0,
    )
    universe = {
        "SPY": bars(smooth_series()),
        "QQQ": bars(choppy_series()),
    }
    positions = {
        "QQQ": PositionSnapshot(symbol="QQQ", quantity=3, market_price=101),
    }

    plan = strategy.build_plan(universe, positions)

    assert plan.selected_symbol == "QQQ"
    assert plan.orders == ()


def test_build_plan_moves_to_cash_when_market_filter_is_off() -> None:
    strategy = QualityLowVolRotationStrategy(
        lookback=252,
        volatility_window=63,
        max_annualized_volatility=1.0,
        market_filter_window=5,
    )
    universe = {
        "SPY": bars([100, 99, 98, 97, 96, 95, 94]),
        "QQQ": bars(smooth_series(7)),
    }
    positions = {
        "QQQ": PositionSnapshot(symbol="QQQ", quantity=3, market_price=101),
    }

    plan = strategy.build_plan(universe, positions)

    assert plan.selected_symbol is None
    assert len(plan.orders) == 1
    assert plan.orders[0].contract.symbol == "QQQ"
    assert plan.orders[0].side == Side.SELL
