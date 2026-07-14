from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from ibkr_quant_bot.broker import BrokerError, IbkrBroker
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import TradeRequest
from ibkr_quant_bot.models import Bar


class FakeIB:
    def __init__(self, account: str, position: float = 0, trades=None):
        self.account = account
        self.position = position
        self.trades = list(trades or [])

    def managedAccounts(self):
        return [self.account]

    def positions(self):
        if self.position == 0:
            return []
        return [
            SimpleNamespace(
                account=self.account,
                contract=SimpleNamespace(symbol="SOXL"),
                position=self.position,
            )
        ]

    def reqAllOpenOrders(self):
        return self.trades

    def openTrades(self):
        return self.trades

    def reqCompletedOrders(self, apiOnly=True):
        return []

    def placeOrder(self, contract, order):
        trade = SimpleNamespace(
            contract=contract,
            order=order,
            orderStatus=SimpleNamespace(
                status="Submitted", filled=0, remaining=order.totalQuantity
            ),
        )
        self.trades.append(trade)
        return trade

    def sleep(self, seconds):
        return None

    def reqCurrentTime(self):
        return datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc)


def make_broker(settings: Settings, fake_ib: FakeIB) -> IbkrBroker:
    broker = object.__new__(IbkrBroker)
    broker.settings = settings
    broker._ib = fake_ib
    return broker


class BrokerSafetyTest(unittest.TestCase):
    def test_heartbeat_returns_gateway_server_time(self) -> None:
        broker = make_broker(Settings(), FakeIB("DU123456"))

        self.assertEqual(
            datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
            broker.server_time(),
        )

    def test_market_session_detects_holiday(self) -> None:
        broker = object.__new__(IbkrBroker)
        broker._stock_contract = lambda symbol: object()
        broker._ib = SimpleNamespace(
            reqContractDetails=lambda _: [
                SimpleNamespace(
                    liquidHours="20261126:CLOSED;20261127:0930-20261127:1300",
                    timeZoneId="America/New_York",
                )
            ]
        )

        self.assertIsNone(broker.market_session("QQQ", date(2026, 11, 26)))

    def test_market_session_uses_ibkr_early_close(self) -> None:
        broker = object.__new__(IbkrBroker)
        broker._stock_contract = lambda symbol: object()
        broker._ib = SimpleNamespace(
            reqContractDetails=lambda _: [
                SimpleNamespace(
                    liquidHours="20261126:CLOSED;20261127:0930-20261127:1300",
                    timeZoneId="America/New_York",
                )
            ]
        )

        session = broker.market_session("QQQ", date(2026, 11, 27))

        self.assertIsNotNone(session)
        self.assertEqual(9, session.opens_at.hour)
        self.assertEqual(30, session.opens_at.minute)
        self.assertEqual(13, session.closes_at.hour)

    def test_historical_pagination_moves_end_time_backward_and_deduplicates(
        self,
    ) -> None:
        broker = object.__new__(IbkrBroker)
        broker.settings = Settings(historical_request_pause_seconds=0)
        broker._ib = SimpleNamespace(sleep=lambda _: None)
        calls = []
        first = datetime(2026, 7, 9, tzinfo=timezone.utc)
        second = datetime(2026, 7, 3, tzinfo=timezone.utc)
        responses = [
            [Bar(first, 1, 1, 1, 1, 1), Bar(second, 2, 2, 2, 2, 2)],
            [
                Bar(second, 2, 2, 2, 2, 2),
                Bar(datetime(2026, 6, 27, tzinfo=timezone.utc), 3, 3, 3, 3, 3),
            ],
            [],
        ]

        def historical(symbol, duration, bar_size, what_to_show, end_time):
            calls.append(end_time)
            return responses.pop(0)

        broker.historical_bars = historical
        rows = broker.historical_bars_paged(
            "SOXL",
            "14 D",
            end_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(3, len(rows))
        self.assertGreater(calls[0], calls[1])
        self.assertGreater(calls[1], calls[2])

    def test_account_environment_mismatch_fails_closed(self) -> None:
        broker = make_broker(Settings(trading_mode="paper"), FakeIB("U123456"))

        with self.assertRaisesRegex(BrokerError, "is live"):
            broker._resolved_trading_account()

    def test_paper_account_is_verified_from_gateway_account(self) -> None:
        broker = make_broker(Settings(trading_mode="paper"), FakeIB("DU123456"))

        self.assertEqual("DU123456", broker._resolved_trading_account())

    def test_broker_preflight_rejects_reduce_only_oversell(self) -> None:
        broker = make_broker(
            Settings(trading_mode="paper"), FakeIB("DU123456", position=2)
        )
        request = TradeRequest("SOXL", "SELL", 3, reduce_only=True)

        with self.assertRaisesRegex(BrokerError, "exceeds long position 2"):
            broker._preflight_order(request)

    def test_broker_preflight_rejects_duplicate_active_order(self) -> None:
        trade = SimpleNamespace(
            contract=SimpleNamespace(symbol="SOXL"),
            order=SimpleNamespace(permId=1, orderId=2, action="BUY"),
            orderStatus=SimpleNamespace(remaining=1),
        )
        broker = make_broker(
            Settings(trading_mode="paper"), FakeIB("DU123456", trades=[trade])
        )

        with self.assertRaisesRegex(BrokerError, "active BUY order"):
            broker._preflight_order(TradeRequest("SOXL", "BUY", 1))

    def test_broker_preflight_requires_explicit_live_enable(self) -> None:
        broker = make_broker(Settings(trading_mode="live"), FakeIB("U123456"))

        with self.assertRaisesRegex(BrokerError, "live trading is disabled"):
            broker._preflight_order(TradeRequest("SOXL", "BUY", 1))

    def test_protective_orders_share_oca_group(self) -> None:
        fake_ib = FakeIB("DU123456", position=2)
        broker = make_broker(Settings(trading_mode="paper", readonly=False), fake_ib)
        broker._stock_contract = lambda symbol: SimpleNamespace(symbol=symbol)
        broker._stop_order = lambda action, quantity, price: SimpleNamespace(
            action=action, totalQuantity=quantity, auxPrice=price
        )
        broker._limit_order = lambda action, quantity, price: SimpleNamespace(
            action=action, totalQuantity=quantity, lmtPrice=price
        )

        stop_trade, take_trade = broker.place_protective_oca(
            "SOXL", 2, 90.0, 110.0, order_ref="momentum-test-protect"
        )

        self.assertEqual(stop_trade.order.ocaGroup, take_trade.order.ocaGroup)
        self.assertEqual(2, stop_trade.order.ocaType)
        self.assertEqual(2, take_trade.order.ocaType)
        self.assertEqual("momentum-test-protect-stop", stop_trade.order.orderRef)
        self.assertEqual("momentum-test-protect-take", take_trade.order.orderRef)


if __name__ == "__main__":
    unittest.main()
