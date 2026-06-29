from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LMT"
    MARKET = "MKT"


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    security_type: str = "STK"


@dataclass(frozen=True)
class OrderIntent:
    contract: ContractSpec
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: float | None
    reason: str
    created_at: datetime

    @property
    def estimated_notional(self) -> float:
        if self.limit_price is None:
            return 0.0
        return abs(self.quantity * self.limit_price)

    @classmethod
    def limit(
        cls,
        symbol: str,
        side: Side,
        quantity: int,
        limit_price: float,
        reason: str,
    ) -> "OrderIntent":
        return cls(
            contract=ContractSpec(symbol=symbol.upper()),
            side=side,
            quantity=quantity,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            reason=reason,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: float
    market_price: float

    @property
    def notional(self) -> float:
        return abs(self.quantity * self.market_price)


@dataclass(frozen=True)
class RiskState:
    positions: dict[str, PositionSnapshot]
    orders_today: int
    realized_pnl_today: float


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reasons: tuple[str, ...]

