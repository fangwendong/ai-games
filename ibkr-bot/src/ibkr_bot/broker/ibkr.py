from __future__ import annotations

from contextlib import AbstractContextManager
import math
from typing import Any

from ibkr_bot.config import Settings
from ibkr_bot.models import ContractSpec, OrderIntent, PositionSnapshot, QuoteSnapshot
from ibkr_bot.strategy.base import Bar


class IbkrBroker(AbstractContextManager["IbkrBroker"]):
    BALANCE_TAGS = (
        "NetLiquidation",
        "TotalCashValue",
        "SettledCash",
        "AccruedCash",
        "BuyingPower",
        "AvailableFunds",
        "ExcessLiquidity",
        "FullInitMarginReq",
        "FullMaintMarginReq",
        "GrossPositionValue",
        "UnrealizedPnL",
        "RealizedPnL",
    )

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

    def balance(self) -> list[Any]:
        self._require_connection()
        tags = set(self.BALANCE_TAGS)
        return [row for row in self.account_summary() if getattr(row, "tag", "") in tags]

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

    def quote(self, contract: ContractSpec) -> QuoteSnapshot:
        from ib_insync import Stock

        self._require_connection()
        ib_contract = Stock(contract.symbol, contract.exchange, contract.currency)
        ticker = self.ib.reqTickers(ib_contract)[0]

        bid = _clean_number(getattr(ticker, "bid", None))
        ask = _clean_number(getattr(ticker, "ask", None))
        last = _clean_number(getattr(ticker, "last", None))
        close = _clean_number(getattr(ticker, "close", None))
        market_price = _clean_number(ticker.marketPrice())
        volume_raw = getattr(ticker, "volume", None)
        volume = int(volume_raw) if isinstance(volume_raw, (int, float)) and volume_raw == volume_raw else None
        timestamp = str(getattr(ticker, "time", None) or "") or None

        source = "live"
        if market_price is None:
            if close is not None:
                market_price = close
                source = "historical-close"
            else:
                source = "unavailable"

        return QuoteSnapshot(
            symbol=contract.symbol,
            source=source,
            bid=bid,
            ask=ask,
            last=last,
            close=close,
            market_price=market_price,
            volume=volume,
            timestamp=timestamp,
        )

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


def _clean_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
