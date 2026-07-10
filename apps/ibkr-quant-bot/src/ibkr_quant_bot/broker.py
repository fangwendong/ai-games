from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .config import Settings
from .models import Bar, Quote, TradeRequest


class BrokerError(RuntimeError):
    pass


def _clean_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number) or number <= 0:
        return None
    return number


class IbkrBroker:
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

    def __init__(self, settings: Settings):
        self.settings = settings
        try:
            from ib_insync import IB, LimitOrder, MarketOrder, Stock  # type: ignore
        except ImportError as exc:
            raise BrokerError("Install dependencies first: pip install -e .") from exc

        self._ib = IB()
        self._limit_order = LimitOrder
        self._market_order = MarketOrder
        self._stock = Stock

    def connect(self) -> None:
        type(self._ib).RequestTimeout = self.settings.request_timeout
        self._ib.connect(
            self.settings.host,
            self.settings.port,
            clientId=self.settings.client_id,
            timeout=self.settings.request_timeout,
            readonly=self.settings.readonly,
        )
        self._set_market_data_type(self.settings.market_data_type)

    def _set_market_data_type(self, market_data_type: str) -> int:
        data_types = {"live": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}
        resolved = data_types.get(market_data_type, 3)
        self._ib.reqMarketDataType(resolved)
        return resolved

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    def _stock_contract(self, symbol: str, exchange: str = "SMART", currency: str = "USD") -> Any:
        contract = self._stock(symbol.upper(), exchange, currency)
        qualified = self._ib.qualifyContracts(contract)
        if not qualified:
            raise BrokerError(f"could not qualify stock contract for {symbol}")
        return qualified[0]

    def _quote_with_type(self, symbol: str, market_data_type: str) -> Quote:
        self._set_market_data_type(market_data_type)
        contract = self._stock_contract(symbol)
        ticker = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)
        self._ib.cancelMktData(contract)
        return Quote(
            symbol=symbol.upper(),
            bid=_clean_number(ticker.bid),
            ask=_clean_number(ticker.ask),
            last=_clean_number(ticker.last),
            close=_clean_number(ticker.close),
        )

    def quote(self, symbol: str) -> Quote:
        mode = (self.settings.market_data_type or "auto").strip().lower()
        if mode == "auto":
            live_quote = self._quote_with_type(symbol, "live")
            if live_quote.bid is not None or live_quote.ask is not None or live_quote.last is not None:
                return live_quote
            return self._quote_with_type(symbol, "delayed")
        return self._quote_with_type(symbol, mode)

    def live_quote(self, symbol: str) -> Quote:
        quote = self._quote_with_type(symbol, "live")
        if quote.bid is None and quote.ask is None and quote.last is None:
            raise BrokerError(f"live quote unavailable for {symbol}; refusing to use delayed data")
        return quote

    def historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
    ) -> list[Bar]:
        contract = self._stock_contract(symbol)
        rows = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=True,
            formatDate=1,
        )
        return [
            Bar(
                time=row.date if isinstance(row.date, datetime) else datetime.combine(row.date, datetime.min.time()),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in rows
        ]

    def account_summary(self) -> list[dict[str, str]]:
        rows = self._ib.accountSummary(self.settings.account or "")
        return [
            {
                "account": str(row.account),
                "tag": str(row.tag),
                "value": str(row.value),
                "currency": str(row.currency),
            }
            for row in rows
        ]

    def balance(self) -> list[dict[str, str]]:
        tags = set(self.BALANCE_TAGS)
        return [row for row in self.account_summary() if row["tag"] in tags]

    def positions(self) -> list[dict[str, str]]:
        return [
            {
                "account": str(position.account),
                "symbol": str(position.contract.symbol),
                "secType": str(position.contract.secType),
                "exchange": str(position.contract.exchange),
                "currency": str(position.contract.currency),
                "position": str(position.position),
                "avgCost": str(position.avgCost),
            }
            for position in self._ib.positions()
        ]

    def place_order(self, request: TradeRequest) -> Any:
        if self.settings.readonly:
            raise BrokerError("IBKR_READONLY=true; refusing to submit orders")
        contract = self._stock_contract(request.symbol)
        if request.order_type.upper() == "LMT":
            order = self._limit_order(request.action.upper(), request.quantity, request.limit_price)
        else:
            order = self._market_order(request.action.upper(), request.quantity)
        if self.settings.account:
            order.account = self.settings.account
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1)
        return trade

    def market_clock(self) -> datetime:
        return datetime.utcnow()


def format_table(rows: Iterable[dict[str, str]], columns: list[str]) -> str:
    rows = list(rows)
    if not rows:
        return "(no rows)"
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    sep = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns)
        for row in rows
    ]
    return "\n".join([header, sep, *body])
