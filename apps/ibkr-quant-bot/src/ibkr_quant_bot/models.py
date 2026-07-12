from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketSession:
    session_date: date
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    close: float | None

    @property
    def reference_price(self) -> float:
        for candidate in (self.ask, self.last, self.close, self.bid):
            if candidate is not None and candidate > 0:
                return float(candidate)
        return 0.0


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    action: str
    quantity: int
    order_type: str = "MKT"
    limit_price: float | None = None
    time_in_force: str | None = None
    order_ref: str | None = None
    reduce_only: bool = False


@dataclass(frozen=True)
class StrategyDecision:
    symbol: str
    action: str
    quantity: int
    reference_price: float
    limit_price: float | None
    reason: str
    signal: bool
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
