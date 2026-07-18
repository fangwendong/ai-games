from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from ibkr_quant_bot.broker import BrokerError, IbkrBroker
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import TradeRequest
from ibkr_quant_bot.models import Bar


class StopStreaming(RuntimeError):
    pass


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


class StreamingIB:
    def __init__(self, missing: set[str] | None = None):
        self.missing = missing or set()
        self.cancelled: list[str] = []
        self.market_data_types: list[int] = []
        self.requests: list[tuple[str, bool]] = []
        self.tickers: dict[str, SimpleNamespace] = {}
        self.update = 0

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_types.append(market_data_type)

    def qualifyContracts(self, *contracts):
        return list(contracts)

    def reqMktData(
        self,
        contract,
        genericTickList,
        snapshot,
        regulatorySnapshot,
    ):
        self.requests.append((contract.symbol, snapshot))
        missing = contract.symbol in self.missing
        ticker = SimpleNamespace(
            marketDataType=1,
            time=datetime.now(timezone.utc),
            rtTime=datetime.now(timezone.utc),
            bid=None if missing else 10.0,
            ask=None if missing else 10.1,
            last=None if missing else 10.05,
            close=10.0,
        )
        self.tickers[contract.symbol] = ticker
        return ticker

    def reqTickers(self, *contracts):
        rows = []
        for contract in contracts:
            missing = contract.symbol in self.missing
            rows.append(
                SimpleNamespace(
                    marketDataType=1,
                    bid=None if missing else 10.0,
                    ask=None if missing else 10.1,
                    last=None if missing else 10.05,
                    close=10.0,
                )
            )
        return rows

    def sleep(self, seconds: float) -> None:
        self.update += 1
        for ticker in self.tickers.values():
            ticker.time = datetime.now(timezone.utc)
            if ticker.last is not None:
                ticker.last += 0.001
        if self.update >= 3:
            raise StopStreaming

    def cancelMktData(self, contract) -> None:
        self.cancelled.append(contract.symbol)


def make_streaming_broker(fake_ib: StreamingIB) -> IbkrBroker:
    broker = object.__new__(IbkrBroker)
    broker.settings = Settings()
    broker._ib = fake_ib
    broker._stock = lambda symbol, exchange, currency: SimpleNamespace(
        symbol=symbol, exchange=exchange, currency=currency
    )
    return broker


def make_broker(settings: Settings, fake_ib: FakeIB) -> IbkrBroker:
    broker = object.__new__(IbkrBroker)
    broker.settings = settings
    broker._ib = fake_ib
    return broker


class BrokerSafetyTest(unittest.TestCase):
    def test_live_quote_snapshots_request_complete_group_without_sleep(
        self,
    ) -> None:
        fake_ib = StreamingIB()
        broker = make_streaming_broker(fake_ib)

        quotes = broker.live_quote_snapshots(["QQQ", "SOXL", "SOXS"])

        self.assertEqual({"QQQ", "SOXL", "SOXS"}, set(quotes))
        self.assertEqual([1], fake_ib.market_data_types)
        self.assertEqual(0, fake_ib.update)

    def test_stream_live_quotes_subscribes_group_and_cancels_on_exit(self) -> None:
        fake_ib = StreamingIB()
        broker = make_streaming_broker(fake_ib)
        updates = []

        with self.assertRaises(StopStreaming):
            broker.stream_live_quotes(
                ["QQQ", "SOXL", "SOXS"],
                lambda quotes, market_times, received_times, observed_at: updates.append(
                    quotes
                ),
                poll_interval_seconds=0.001,
            )

        self.assertTrue(updates)
        self.assertEqual(
            [("QQQ", False), ("SOXL", False), ("SOXS", False)],
            fake_ib.requests,
        )
        self.assertEqual(["QQQ", "SOXL", "SOXS"], fake_ib.cancelled)

    def test_live_quote_snapshots_fail_closed_on_missing_symbol(self) -> None:
        fake_ib = StreamingIB({"SOXS"})
        broker = make_streaming_broker(fake_ib)

        with self.assertRaisesRegex(BrokerError, "SOXS"):
            broker.live_quote_snapshots(["QQQ", "SOXL", "SOXS"])

    def test_live_quote_snapshots_reject_delayed_market_data_type(self) -> None:
        fake_ib = StreamingIB()
        broker = make_streaming_broker(fake_ib)
        original = fake_ib.reqTickers

        def delayed(*contracts):
            rows = original(*contracts)
            rows[1].marketDataType = 3
            return rows

        fake_ib.reqTickers = delayed

        with self.assertRaisesRegex(BrokerError, "type 3.*SOXL"):
            broker.live_quote_snapshots(["QQQ", "SOXL", "SOXS"])

    def test_stream_live_quotes_rejects_delayed_market_data_type(self) -> None:
        fake_ib = StreamingIB()
        broker = make_streaming_broker(fake_ib)
        original = fake_ib.reqMktData

        def delayed_soxs(contract, *args, **kwargs):
            ticker = original(contract, *args, **kwargs)
            if contract.symbol == "SOXS":
                ticker.marketDataType = 3
            return ticker

        fake_ib.reqMktData = delayed_soxs

        with self.assertRaisesRegex(BrokerError, "type 3.*SOXS"):
            broker.stream_live_quotes(
                ["QQQ", "SOXL", "SOXS"], lambda *_: None, poll_interval_seconds=0.001
            )

        self.assertEqual(["QQQ", "SOXL", "SOXS"], fake_ib.cancelled)

    def test_stream_live_quotes_rejects_nonpositive_poll_interval(self) -> None:
        broker = make_streaming_broker(StreamingIB())

        with self.assertRaisesRegex(ValueError, "poll_interval_seconds"):
            broker.stream_live_quotes(["QQQ"], lambda *_: None, poll_interval_seconds=0)

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

    def test_historical_market_sessions_use_dedicated_ibkr_schedule(self) -> None:
        broker = object.__new__(IbkrBroker)
        contract = object()
        broker._stock_contract = lambda symbol: contract
        calls = []

        def historical_schedule(
            requested_contract, *, numDays, endDateTime, useRTH
        ):
            calls.append((requested_contract, numDays, endDateTime, useRTH))
            return SimpleNamespace(
                timeZone="US/Eastern",
                sessions=[
                    SimpleNamespace(
                        refDate="20260713",
                        startDateTime="20260713-09:30:00",
                        endDateTime="20260713-16:00:00",
                    ),
                    SimpleNamespace(
                        refDate="20260714",
                        startDateTime="20260714-09:30:00",
                        endDateTime="20260714-13:00:00",
                    ),
                ],
            )

        broker._ib = SimpleNamespace(reqHistoricalSchedule=historical_schedule)
        end = datetime(2026, 7, 15, tzinfo=timezone.utc)

        sessions = broker.historical_market_sessions(
            "QQQ", num_days=10, end_datetime=end
        )

        self.assertEqual([(contract, 10, end, True)], calls)
        self.assertEqual(9, sessions[date(2026, 7, 13)].opens_at.hour)
        self.assertEqual(16, sessions[date(2026, 7, 13)].closes_at.hour)
        self.assertEqual(13, sessions[date(2026, 7, 14)].closes_at.hour)
        self.assertEqual("US/Eastern", sessions[date(2026, 7, 14)].opens_at.tzinfo.key)

    def test_historical_market_sessions_fail_closed_on_empty_response(self) -> None:
        broker = object.__new__(IbkrBroker)
        broker._stock_contract = lambda symbol: object()
        broker._ib = SimpleNamespace(
            reqHistoricalSchedule=lambda *args, **kwargs: SimpleNamespace(
                timeZone="US/Eastern", sessions=[]
            )
        )

        with self.assertRaisesRegex(BrokerError, "no historical sessions"):
            broker.historical_market_sessions("QQQ", num_days=10)

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

        def historical(
            symbol,
            duration,
            bar_size,
            what_to_show,
            end_time,
            exchange="SMART",
        ):
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

    def test_historical_pagination_picks_smaller_chunks_for_subminute_bars(
        self,
    ) -> None:
        broker = object.__new__(IbkrBroker)
        broker.settings = Settings(historical_request_pause_seconds=0)
        broker._ib = SimpleNamespace(sleep=lambda _: None)
        calls = []

        def historical(
            symbol,
            duration,
            bar_size,
            what_to_show,
            end_time,
            exchange="SMART",
        ):
            calls.append((duration, bar_size))
            return []

        broker.historical_bars = historical
        broker.historical_bars_paged(
            "SOXL",
            "3 D",
            bar_size="30 secs",
            end_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        self.assertEqual([("1 D", "30 secs")], calls)

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

    def test_complete_protective_oca_requires_both_matching_legs(self) -> None:
        group = "oca-test"

        def leg(order_ref, order_type):
            return SimpleNamespace(
                contract=SimpleNamespace(symbol="SOXL"),
                order=SimpleNamespace(
                    permId=order_ref,
                    orderId=order_ref,
                    action="SELL",
                    orderRef=order_ref,
                    orderType=order_type,
                    ocaGroup=group,
                ),
                orderStatus=SimpleNamespace(remaining=5),
            )

        prefix = "momentum-2026-07-16-SOXL-protect"
        stop = leg(f"{prefix}-stop", "STP")
        take = leg(f"{prefix}-take", "LMT")
        broker = make_broker(
            Settings(trading_mode="paper"), FakeIB("DU123456", trades=[stop, take])
        )

        self.assertTrue(
            broker.protective_oca_is_complete(
                "SOXL", 5, order_ref_prefix=prefix
            )
        )
        broker._ib.trades = [stop]
        self.assertFalse(
            broker.protective_oca_is_complete(
                "SOXL", 5, order_ref_prefix=prefix
            )
        )

    def test_filled_order_ref_prefix_recovers_missing_entry_state(self) -> None:
        trade = SimpleNamespace(
            contract=SimpleNamespace(symbol="SOXL"),
            order=SimpleNamespace(
                permId=1,
                orderId=2,
                action="BUY",
                orderRef="momentum-2026-07-16-SOXL-entry-101500",
            ),
            orderStatus=SimpleNamespace(filled=3, remaining=0),
            fills=[],
        )
        broker = make_broker(
            Settings(trading_mode="paper"), FakeIB("DU123456", trades=[trade])
        )

        self.assertTrue(
            broker.filled_order_ref_prefix_exists(
                "momentum-2026-07-16-SOXL-entry-"
            )
        )
        self.assertEqual(
            1,
            broker.filled_order_ref_prefix_count(
                "momentum-2026-07-16-SOXL-entry-"
            ),
        )
        self.assertFalse(
            broker.filled_order_ref_prefix_exists(
                "momentum-2026-07-16-SOXS-entry-"
            )
        )

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
