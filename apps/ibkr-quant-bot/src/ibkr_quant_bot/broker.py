from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .models import Bar, MarketSession, Quote, TradeRequest


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
            from ib_insync import IB, LimitOrder, MarketOrder, Stock, StopOrder  # type: ignore
        except ImportError as exc:
            raise BrokerError("Install dependencies first: pip install -e .") from exc

        self._ib = IB()
        self._limit_order = LimitOrder
        self._market_order = MarketOrder
        self._stop_order = StopOrder
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

    def server_time(self) -> datetime:
        """Round-trip a lightweight request to verify the API session."""
        value = self._ib.reqCurrentTime()
        if not isinstance(value, datetime):
            raise BrokerError("IBKR heartbeat returned an invalid server time")
        return value

    def market_session(self, symbol: str, session_date: date) -> MarketSession | None:
        """Return IBKR's regular/liquid session, or None for an explicit closure."""
        contract = self._stock_contract(symbol)
        details = self._ib.reqContractDetails(contract)
        if not details:
            raise BrokerError(f"IBKR returned no contract details for {symbol}")
        detail = details[0]
        liquid_hours = str(getattr(detail, "liquidHours", "") or "")
        timezone_id = str(getattr(detail, "timeZoneId", "") or "")
        try:
            session_timezone = ZoneInfo(timezone_id or "America/New_York")
        except Exception as exc:
            raise BrokerError(
                f"unsupported IBKR trading-hours timezone for {symbol}: {timezone_id!r}"
            ) from exc

        day_key = session_date.strftime("%Y%m%d")
        matching = [
            item for item in liquid_hours.split(";") if item.startswith(f"{day_key}:")
        ]
        if not matching:
            raise BrokerError(
                f"IBKR liquid-hours calendar has no {session_date.isoformat()} entry for {symbol}"
            )
        if all(value.split(":", 1)[1].upper() == "CLOSED" for value in matching):
            return None

        intervals: list[tuple[datetime, datetime]] = []
        for value in matching:
            payload = value.split(":", 1)[1]
            if payload.upper() == "CLOSED":
                continue
            for interval in payload.split(","):
                try:
                    start_text, end_text = interval.split("-", 1)
                    if ":" not in start_text:
                        start_text = f"{day_key}:{start_text}"
                    if ":" not in end_text:
                        end_text = f"{day_key}:{end_text}"
                    start = datetime.strptime(start_text, "%Y%m%d:%H%M").replace(
                        tzinfo=session_timezone
                    )
                    end = datetime.strptime(end_text, "%Y%m%d:%H%M").replace(
                        tzinfo=session_timezone
                    )
                except ValueError as exc:
                    raise BrokerError(
                        f"invalid IBKR liquid-hours entry for {symbol}: {interval!r}"
                    ) from exc
                intervals.append((start, end))
        if not intervals:
            raise BrokerError(
                f"IBKR liquid-hours calendar has no usable session for {symbol} on {session_date.isoformat()}"
            )
        return MarketSession(
            session_date=session_date,
            opens_at=min(start for start, _ in intervals),
            closes_at=max(end for _, end in intervals),
        )

    def historical_market_sessions(
        self,
        symbol: str,
        *,
        num_days: int,
        end_datetime: datetime | date | str | None = None,
    ) -> dict[date, MarketSession]:
        """Return IBKR's historical regular-session schedule keyed by date.

        Contract ``liquidHours`` is intended for the current trading calendar and
        may omit past dates. Historical cache validation must use IBKR's dedicated
        historical schedule request instead.
        """
        if num_days < 1:
            raise ValueError("num_days must be positive")

        contract = self._stock_contract(symbol)
        schedule = self._ib.reqHistoricalSchedule(
            contract,
            numDays=num_days,
            endDateTime=end_datetime or "",
            useRTH=True,
        )
        timezone_id = str(getattr(schedule, "timeZone", "") or "America/New_York")
        try:
            session_timezone = ZoneInfo(timezone_id)
        except Exception as exc:
            raise BrokerError(
                f"unsupported IBKR historical-schedule timezone for {symbol}: {timezone_id!r}"
            ) from exc

        def parse_timestamp(value: object) -> datetime:
            if isinstance(value, datetime):
                parsed = value
            else:
                try:
                    parsed = datetime.strptime(str(value), "%Y%m%d-%H:%M:%S")
                except ValueError as exc:
                    raise BrokerError(
                        f"invalid IBKR historical-schedule timestamp for {symbol}: {value!r}"
                    ) from exc
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=session_timezone)
            return parsed.astimezone(session_timezone)

        sessions: dict[date, MarketSession] = {}
        for row in list(getattr(schedule, "sessions", []) or []):
            try:
                session_date = datetime.strptime(str(row.refDate), "%Y%m%d").date()
            except (AttributeError, ValueError) as exc:
                raise BrokerError(
                    f"invalid IBKR historical-schedule date for {symbol}: "
                    f"{getattr(row, 'refDate', None)!r}"
                ) from exc
            opens_at = parse_timestamp(getattr(row, "startDateTime", None))
            closes_at = parse_timestamp(getattr(row, "endDateTime", None))
            if closes_at <= opens_at:
                raise BrokerError(
                    f"invalid IBKR historical session for {symbol} on "
                    f"{session_date.isoformat()}: close is not after open"
                )
            sessions[session_date] = MarketSession(
                session_date=session_date,
                opens_at=opens_at,
                closes_at=closes_at,
            )

        if not sessions:
            raise BrokerError(f"IBKR returned no historical sessions for {symbol}")
        return sessions

    def _stock_contract(
        self, symbol: str, exchange: str = "SMART", currency: str = "USD"
    ) -> Any:
        contract = self._stock(symbol.upper(), exchange, currency)
        qualified = self._ib.qualifyContracts(contract)
        if not qualified:
            raise BrokerError(f"could not qualify stock contract for {symbol}")
        return qualified[0]

    def _quote_with_type(
        self,
        symbol: str,
        market_data_type: str,
        *,
        exchange: str = "SMART",
    ) -> Quote:
        self._set_market_data_type(market_data_type)
        contract = self._stock_contract(symbol, exchange=exchange)
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

    def quote(self, symbol: str, *, exchange: str = "SMART") -> Quote:
        mode = (self.settings.market_data_type or "auto").strip().lower()
        if mode == "auto":
            live_quote = self._quote_with_type(symbol, "live", exchange=exchange)
            if (
                live_quote.bid is not None
                or live_quote.ask is not None
                or live_quote.last is not None
            ):
                return live_quote
            return self._quote_with_type(symbol, "delayed", exchange=exchange)
        return self._quote_with_type(symbol, mode, exchange=exchange)

    def live_quote(self, symbol: str, *, exchange: str = "SMART") -> Quote:
        quote = self._quote_with_type(symbol, "live", exchange=exchange)
        if quote.bid is None and quote.ask is None and quote.last is None:
            raise BrokerError(
                f"live quote unavailable for {symbol}; refusing to use delayed data"
            )
        return quote

    def live_quote_snapshots(
        self,
        symbols: Iterable[str],
        *,
        exchange: str = "SMART",
    ) -> dict[str, Quote]:
        """Request one concurrent live snapshot group without a fixed sleep."""
        normalized_symbols = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        if not normalized_symbols:
            raise ValueError("symbols must not be empty")
        self._set_market_data_type("live")
        requested = [
            self._stock(symbol, exchange, "USD") for symbol in normalized_symbols
        ]
        qualified = self._ib.qualifyContracts(*requested)
        if len(qualified) != len(requested):
            raise BrokerError(
                "could not qualify complete live quote group: "
                + ", ".join(normalized_symbols)
            )
        quotes: dict[str, Quote] = {}
        missing: list[str] = []
        tickers = self._ib.reqTickers(*qualified)
        if len(tickers) != len(normalized_symbols):
            raise BrokerError("IBKR returned an incomplete live quote snapshot group")
        for symbol, ticker in zip(normalized_symbols, tickers, strict=True):
            quote = Quote(
                symbol=symbol,
                bid=_clean_number(ticker.bid),
                ask=_clean_number(ticker.ask),
                last=_clean_number(ticker.last),
                close=_clean_number(ticker.close),
            )
            if quote.bid is None and quote.ask is None and quote.last is None:
                missing.append(symbol)
            else:
                quotes[symbol] = quote
        if missing:
            raise BrokerError(
                "live quote unavailable for "
                + ", ".join(missing)
                + "; refusing to use delayed data"
            )
        return quotes

    def stream_live_quotes(
        self,
        symbols: Iterable[str],
        consumer: Callable[[dict[str, Quote], datetime], None],
        *,
        exchange: str = "SMART",
        poll_interval_seconds: float = 0.02,
    ) -> None:
        """Continuously consume a concurrent live subscription until interrupted."""
        normalized_symbols = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        if not normalized_symbols:
            raise ValueError("symbols must not be empty")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._set_market_data_type("live")
        requested = [
            self._stock(symbol, exchange, "USD") for symbol in normalized_symbols
        ]
        qualified = self._ib.qualifyContracts(*requested)
        if len(qualified) != len(requested):
            raise BrokerError(
                "could not qualify complete live quote stream group: "
                + ", ".join(normalized_symbols)
            )
        contracts = dict(zip(normalized_symbols, qualified, strict=True))
        tickers: dict[str, Any] = {}
        subscribed: list[Any] = []
        signatures: dict[str, tuple[object, ...]] = {}
        try:
            for symbol, contract in contracts.items():
                tickers[symbol] = self._ib.reqMktData(
                    contract, "", snapshot=False, regulatorySnapshot=False
                )
                subscribed.append(contract)
            while True:
                self._ib.sleep(poll_interval_seconds)
                is_connected = getattr(self._ib, "isConnected", None)
                if callable(is_connected) and not is_connected():
                    raise BrokerError("IBKR live quote stream disconnected")
                observed_at = datetime.now(timezone.utc)
                changed: dict[str, Quote] = {}
                for symbol, ticker in tickers.items():
                    quote = Quote(
                        symbol=symbol,
                        bid=_clean_number(ticker.bid),
                        ask=_clean_number(ticker.ask),
                        last=_clean_number(ticker.last),
                        close=_clean_number(ticker.close),
                    )
                    if quote.bid is None and quote.ask is None and quote.last is None:
                        continue
                    signature = (
                        getattr(ticker, "time", None),
                        quote.bid,
                        quote.ask,
                        quote.last,
                        quote.close,
                    )
                    if signature != signatures.get(symbol):
                        changed[symbol] = quote
                        signatures[symbol] = signature
                consumer(changed, observed_at)
        finally:
            for contract in subscribed:
                try:
                    self._ib.cancelMktData(contract)
                except Exception:
                    pass

    def historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        end_time: datetime | str | None = None,
        exchange: str = "SMART",
    ) -> list[Bar]:
        contract = self._stock_contract(symbol, exchange=exchange)
        rows = self._ib.reqHistoricalData(
            contract,
            endDateTime=end_time or "",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=True,
            formatDate=1,
        )
        return [
            Bar(
                time=row.date
                if isinstance(row.date, datetime)
                else datetime.combine(row.date, datetime.min.time()),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in rows
        ]

    @staticmethod
    def _duration_days(duration: str) -> int:
        parts = duration.strip().upper().split()
        if len(parts) != 2:
            raise ValueError(f"unsupported duration: {duration}")
        try:
            value = int(parts[0])
        except ValueError as exc:
            raise ValueError(f"unsupported duration: {duration}") from exc
        multipliers = {"D": 1, "W": 7, "M": 30, "Y": 365}
        unit = parts[1].rstrip("S")
        if value <= 0 or unit not in multipliers:
            raise ValueError(f"unsupported duration: {duration}")
        return value * multipliers[unit]

    def historical_bars_paged(
        self,
        symbol: str,
        duration: str,
        *,
        bar_size: str = "5 mins",
        what_to_show: str = "TRADES",
        chunk_duration: str = "1 W",
        end_time: datetime | None = None,
        page_callback: Callable[[list[Bar]], None] | None = None,
        exchange: str = "SMART",
    ) -> list[Bar]:
        """Page backward with explicit end times for long intraday histories."""
        end = end_time or datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        cutoff = end - timedelta(days=self._duration_days(duration))
        rows_by_time: dict[datetime, Bar] = {}
        cursor = end
        max_pages = (
            self._duration_days(duration) // max(1, self._duration_days(chunk_duration))
            + 3
        )
        for _ in range(max_pages):
            rows = self.historical_bars(
                symbol,
                duration=chunk_duration,
                bar_size=bar_size,
                what_to_show=what_to_show,
                end_time=cursor,
                exchange=exchange,
            )
            if not rows:
                break
            normalized = [
                (
                    row.time.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(
                        timezone.utc
                    )
                    if row.time.tzinfo is None
                    else row.time.astimezone(timezone.utc),
                    row,
                )
                for row in rows
            ]
            page_rows: list[Bar] = []
            for timestamp, row in normalized:
                if cutoff <= timestamp <= end:
                    rows_by_time[timestamp] = row
                    page_rows.append(row)
            if page_callback is not None and page_rows:
                page_callback(page_rows)
            earliest = min(timestamp for timestamp, _ in normalized)
            if earliest <= cutoff:
                break
            next_cursor = earliest - timedelta(seconds=1)
            if next_cursor >= cursor:
                raise BrokerError(
                    f"historical pagination did not move backward for {symbol}"
                )
            cursor = next_cursor
            self._ib.sleep(max(0.0, self.settings.historical_request_pause_seconds))
        return [rows_by_time[timestamp] for timestamp in sorted(rows_by_time)]

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

    def _resolved_trading_account(self) -> str:
        accounts = [str(account) for account in self._ib.managedAccounts()]
        if self.settings.account:
            if self.settings.account not in accounts:
                raise BrokerError(
                    f"configured account {self.settings.account} is not exposed by Gateway: {accounts}"
                )
            account = self.settings.account
        elif len(accounts) == 1:
            account = accounts[0]
        else:
            raise BrokerError(
                "set IBKR_ACCOUNT when Gateway exposes zero or multiple accounts"
            )

        # IBKR paper account numbers use the DU prefix. A plain U prefix is a
        # production account. Unknown prefixes fail closed rather than trusting
        # IBKR_TRADING_MODE alone.
        if account.upper().startswith("DU"):
            actual_mode = "paper"
        elif account.upper().startswith("U"):
            actual_mode = "live"
        else:
            raise BrokerError(
                f"cannot verify paper/live environment from IBKR account {account}"
            )
        expected_mode = "live" if self.settings.is_live else "paper"
        if actual_mode != expected_mode:
            raise BrokerError(
                f"IBKR account {account} is {actual_mode}, but IBKR_TRADING_MODE={self.settings.trading_mode}"
            )
        return account

    def position_quantity(self, symbol: str) -> float:
        symbol = symbol.upper()
        account = self.settings.account
        quantity = 0.0
        for position in self._ib.positions():
            if str(position.contract.symbol).upper() != symbol:
                continue
            if account and str(position.account) != account:
                continue
            quantity += float(position.position)
        return quantity

    def active_trades(self) -> list[Any]:
        requested = list(self._ib.reqAllOpenOrders())
        cached = list(self._ib.openTrades())
        trades: dict[tuple[object, object], Any] = {}
        for trade in [*requested, *cached]:
            order = getattr(trade, "order", None)
            key = (getattr(order, "permId", None), getattr(order, "orderId", id(trade)))
            trades[key] = trade
        return list(trades.values())

    def completed_trades(self) -> list[Any]:
        return list(self._ib.reqCompletedOrders(apiOnly=True))

    def order_ref_exists(self, order_ref: str) -> bool:
        for trade in [*self.active_trades(), *self.completed_trades()]:
            order = getattr(trade, "order", None)
            if str(getattr(order, "orderRef", "") or "") == order_ref:
                return True
        return False

    @staticmethod
    def _trade_symbol(trade: Any) -> str:
        return str(getattr(getattr(trade, "contract", None), "symbol", "")).upper()

    @staticmethod
    def _trade_action(trade: Any) -> str:
        return str(getattr(getattr(trade, "order", None), "action", "")).upper()

    @staticmethod
    def _trade_remaining(trade: Any) -> float:
        try:
            return float(
                getattr(getattr(trade, "orderStatus", None), "remaining", 0) or 0
            )
        except (TypeError, ValueError):
            return 0.0

    def active_order_quantity(self, symbol: str, action: str) -> float:
        symbol = symbol.upper()
        action = action.upper()
        return sum(
            self._trade_remaining(trade)
            for trade in self.active_trades()
            if self._trade_symbol(trade) == symbol
            and self._trade_action(trade) == action
        )

    def cancel_active_orders(
        self,
        symbol: str,
        action: str | None = None,
        *,
        order_ref_prefix: str | None = None,
    ) -> list[Any]:
        cancelled: list[Any] = []
        for trade in self.active_trades():
            if self._trade_symbol(trade) != symbol.upper():
                continue
            if action is not None and self._trade_action(trade) != action.upper():
                continue
            order_ref = str(
                getattr(getattr(trade, "order", None), "orderRef", "") or ""
            )
            if order_ref_prefix is not None and not order_ref.startswith(
                order_ref_prefix
            ):
                continue
            self.cancel_order(trade)
            cancelled.append(trade)
        return cancelled

    def _apply_common_order_fields(
        self, order: Any, request: TradeRequest, account: str
    ) -> None:
        if request.time_in_force:
            order.tif = request.time_in_force.upper()
        order.account = account
        if request.order_ref:
            order.orderRef = request.order_ref

    def _preflight_order(self, request: TradeRequest) -> str:
        if self.settings.is_live and not self.settings.allow_live_trading:
            raise BrokerError(
                "live trading is disabled by IBKR_ALLOW_LIVE_TRADING=false"
            )
        account = self._resolved_trading_account()
        symbol = request.symbol.upper()
        action = request.action.upper()
        duplicate_quantity = self.active_order_quantity(symbol, action)
        if duplicate_quantity > 0:
            raise BrokerError(
                f"active {action} order already exists for {symbol} (remaining={duplicate_quantity:g})"
            )
        if action == "SELL":
            if not request.reduce_only:
                raise BrokerError("refusing non-reduce-only SELL")
            position = self.position_quantity(symbol)
            if position <= 0 or request.quantity > position:
                raise BrokerError(
                    f"reduce-only SELL quantity {request.quantity} exceeds long position {position:g}"
                )
        return account

    def place_order(self, request: TradeRequest) -> Any:
        if self.settings.readonly:
            raise BrokerError("IBKR_READONLY=true; refusing to submit orders")
        account = self._preflight_order(request)
        contract = self._stock_contract(request.symbol)
        if request.order_type.upper() == "LMT":
            order = self._limit_order(
                request.action.upper(), request.quantity, request.limit_price
            )
        else:
            order = self._market_order(request.action.upper(), request.quantity)
        self._apply_common_order_fields(order, request, account)
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1)
        return trade

    def place_protective_oca(
        self,
        symbol: str,
        quantity: int,
        stop_price: float,
        take_price: float,
        *,
        order_ref: str,
    ) -> tuple[Any, Any]:
        if self.settings.readonly:
            raise BrokerError(
                "IBKR_READONLY=true; refusing to submit protective orders"
            )
        request = TradeRequest(
            symbol=symbol,
            action="SELL",
            quantity=quantity,
            time_in_force="GTC",
            order_ref=order_ref,
            reduce_only=True,
        )
        account = self._preflight_order(request)
        contract = self._stock_contract(symbol)
        stop_order = self._stop_order("SELL", quantity, round(stop_price, 2))
        take_order = self._limit_order("SELL", quantity, round(take_price, 2))
        group = f"ibkrbot-{symbol.upper()}-{uuid.uuid4().hex[:16]}"
        for suffix, order in (("stop", stop_order), ("take", take_order)):
            child_request = TradeRequest(
                symbol=symbol,
                action="SELL",
                quantity=quantity,
                time_in_force="GTC",
                order_ref=f"{order_ref}-{suffix}",
                reduce_only=True,
            )
            self._apply_common_order_fields(order, child_request, account)
            order.ocaGroup = group
            order.ocaType = 2
        stop_trade = self._ib.placeOrder(contract, stop_order)
        take_trade = self._ib.placeOrder(contract, take_order)
        self._ib.sleep(1)
        return stop_trade, take_trade

    def wait_for_trade_update(self, trade: Any, timeout_seconds: float) -> Any:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        terminal_statuses = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
        while time.monotonic() < deadline:
            order_status = getattr(trade, "orderStatus", None)
            if order_status is not None:
                try:
                    filled = float(getattr(order_status, "filled", 0) or 0)
                except (TypeError, ValueError):
                    filled = 0.0
                status = str(getattr(order_status, "status", "") or "")
                if filled > 0 or status in terminal_statuses:
                    return trade
            self._ib.sleep(min(1.0, max(0.1, deadline - time.monotonic())))
        return trade

    def cancel_order(self, trade: Any, timeout_seconds: float = 10.0) -> Any:
        order = getattr(trade, "order", None)
        if order is not None:
            self._ib.cancelOrder(order)
            deadline = time.monotonic() + max(0.0, timeout_seconds)
            while time.monotonic() < deadline:
                status = str(
                    getattr(getattr(trade, "orderStatus", None), "status", "") or ""
                )
                if status in {"Filled", "Cancelled", "ApiCancelled", "Inactive"}:
                    break
                self._ib.sleep(min(0.5, max(0.1, deadline - time.monotonic())))
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
