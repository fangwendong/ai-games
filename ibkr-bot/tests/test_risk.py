from pathlib import Path

from ibkr_bot.config import Settings
from ibkr_bot.models import OrderIntent, OrderType, PositionSnapshot, RiskState, Side
from ibkr_bot.risk import RiskManager


def settings(**overrides: object) -> Settings:
    values = dict(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        symbols=("SPY",),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
    )
    values.update(overrides)
    return Settings(**values)


def empty_state() -> RiskState:
    return RiskState(positions={}, orders_today=0, realized_pnl_today=0)


def test_accepts_small_limit_order() -> None:
    intent = OrderIntent.limit("SPY", Side.BUY, quantity=1, limit_price=400, reason="test")
    decision = RiskManager(settings()).evaluate(intent, empty_state())
    assert decision.accepted
    assert decision.reasons == ()


def test_rejects_oversized_order() -> None:
    intent = OrderIntent.limit("SPY", Side.BUY, quantity=10, limit_price=400, reason="test")
    decision = RiskManager(settings()).evaluate(intent, empty_state())
    assert not decision.accepted
    assert any("max_notional_per_order" in reason for reason in decision.reasons)


def test_rejects_market_order_by_default() -> None:
    intent = OrderIntent(
        contract=OrderIntent.limit("SPY", Side.BUY, 1, 400, "base").contract,
        side=Side.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        limit_price=None,
        reason="test",
        created_at=OrderIntent.limit("SPY", Side.BUY, 1, 400, "base").created_at,
    )
    decision = RiskManager(settings()).evaluate(intent, empty_state())
    assert not decision.accepted
    assert "market orders are disabled" in decision.reasons


def test_rejects_projected_position_limit() -> None:
    intent = OrderIntent.limit("SPY", Side.BUY, quantity=2, limit_price=400, reason="test")
    state = RiskState(
        positions={"SPY": PositionSnapshot(symbol="SPY", quantity=4, market_price=400)},
        orders_today=0,
        realized_pnl_today=0,
    )
    decision = RiskManager(settings()).evaluate(intent, state)
    assert not decision.accepted
    assert any("max_position_notional" in reason for reason in decision.reasons)

