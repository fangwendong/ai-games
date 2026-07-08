from pathlib import Path

from ibkr_bot.broker.ibkr import IbkrBroker
from ibkr_bot.config import Settings
from ibkr_bot.models import OrderIntent, Side


class DummyTrade:
    def __init__(self, order):
        self.order = order


class DummyIB:
    def __init__(self):
        self.connected = True
        self.orders = []

    def isConnected(self):
        return self.connected

    def placeOrder(self, contract, order):
        self.orders.append((contract, order))
        return DummyTrade(order)


def settings(**overrides: object) -> Settings:
    values = dict(
        host="127.0.0.1",
        port=4002,
        client_id=17,
        account=None,
        trading_mode="paper",
        dry_run=True,
        allow_live=False,
        allow_extended_hours=False,
        symbols=("SPY",),
        max_notional_per_order=1000.0,
        max_position_notional=2000.0,
        max_orders_per_day=5,
        max_daily_loss=100.0,
        allow_market_orders=False,
        database_path=Path(":memory:"),
        alert_command=None,
        rotation_symbols=(),
    )
    values.update(overrides)
    return Settings(**values)


def test_place_order_sets_outside_rth_when_enabled() -> None:
    broker = IbkrBroker(settings(allow_extended_hours=True))
    broker.ib = DummyIB()
    intent = OrderIntent.limit("SPY", Side.BUY, quantity=1, limit_price=400, reason="test")

    broker.place_order(intent)

    assert broker.ib.orders[0][1].outsideRth is True


def test_place_order_leaves_outside_rth_disabled_by_default() -> None:
    broker = IbkrBroker(settings())
    broker.ib = DummyIB()
    intent = OrderIntent.limit("SPY", Side.BUY, quantity=1, limit_price=400, reason="test")

    broker.place_order(intent)

    assert broker.ib.orders[0][1].outsideRth is False
