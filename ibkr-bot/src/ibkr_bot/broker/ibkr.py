from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from ibkr_bot.config import Settings
from ibkr_bot.models import ContractSpec, OrderIntent, PositionSnapshot
from ibkr_bot.strategy.base import Bar


class IbkrBroker(AbstractContextManager["IbkrBroker"]):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ib: Any | None = None

    def __enter__(self) -> "IbkrBroker":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.disconnect()

    def connect(self) -> None:
        from ib_insync import IB

        self.ib = IB()
        self.ib.connect(
            self.settings.host,
            self.settings.port,
            clientId=self.settings.client_id,
            account=self.settings.account or "",
            timeout=10,
        )

    def disconnect(self) -> None:
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()

    def server_time(self) -> str:
        self._require_connection()
        return str(self.ib.reqCurrentTime())

    def account_summary(self) -> list[Any]:
        self._require_connection()
        return list(self.ib.accountSummary(account=self.settings.account or ""))

    def positions(self) -> dict[str, PositionSnapshot]:
        self._require_connection()
        snapshots: dict[str, PositionSnapshot] = {}
        for position in self.ib.positions(account=self.settings.account or ""):
            symbol = getattr(position.contract, "symbol", "")
            if symbol:
                snapshots[symbol] = PositionSnapshot(
                    symbol=symbol,
                    quantity=float(position.position),
                    market_price=float(position.avgCost or 0.0),
                )
        return snapshots

    def historical_bars(self, contract: ContractSpec, duration: str = "30 D") -> list[Bar]:
        from ib_insync import Stock, util

        self._require_connection()
        ib_contract = Stock(contract.symbol, contract.exchange, contract.currency)
        bars = self.ib.reqHistoricalData(
            ib_contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        dataframe = util.df(bars)
        if dataframe is None or dataframe.empty:
            return []
        return [
            Bar(timestamp=str(row.date), close=float(row.close))
            for row in dataframe.itertuples(index=False)
        ]

    def place_order(self, intent: OrderIntent) -> str:
        from ib_insync import LimitOrder, MarketOrder, Stock

        self._require_connection()
        contract = Stock(intent.contract.symbol, intent.contract.exchange, intent.contract.currency)
        if intent.order_type.value == "LMT":
            order = LimitOrder(intent.side.value, intent.quantity, intent.limit_price)
        else:
            order = MarketOrder(intent.side.value, intent.quantity)
        trade = self.ib.placeOrder(contract, order)
        return str(getattr(trade.order, "orderId", ""))

    def _require_connection(self) -> None:
        if not self.ib or not self.ib.isConnected():
            raise RuntimeError("IBKR broker is not connected")

