from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .models import RiskDecision, TradeRequest


@dataclass(frozen=True)
class RiskManager:
    settings: Settings

    def validate(
        self,
        request: TradeRequest,
        reference_price: float,
        *,
        position_quantity: float | None = None,
        pending_sell_quantity: float = 0.0,
    ) -> RiskDecision:
        symbol = request.symbol.upper()
        if request.quantity <= 0:
            return RiskDecision(False, "quantity must be positive")

        if self.settings.is_live and not self.settings.allow_live_trading:
            return RiskDecision(
                False, "live trading is disabled by IBKR_ALLOW_LIVE_TRADING=false"
            )

        allowed_symbols = {item.upper() for item in self.settings.allowed_symbols}
        if symbol not in allowed_symbols:
            return RiskDecision(False, f"{symbol} is not in IBKR_ALLOWED_SYMBOLS")

        action = request.action.upper()
        if action not in {"BUY", "SELL"}:
            return RiskDecision(False, f"unsupported action: {action}")

        if action == "SELL":
            if not request.reduce_only:
                return RiskDecision(False, "SELL orders must be marked reduce_only")
            if position_quantity is None:
                return RiskDecision(
                    False, "current position is required for a reduce-only SELL"
                )
            available = max(0.0, position_quantity - max(0.0, pending_sell_quantity))
            if request.quantity > available:
                return RiskDecision(
                    False,
                    f"reduce-only SELL quantity {request.quantity} exceeds available long position {available:g}",
                )
            return RiskDecision(
                True,
                f"validated reduce-only {symbol} sell of {request.quantity}/{position_quantity:g}",
            )

        notional = reference_price * request.quantity
        if notional > self.settings.max_order_notional:
            return RiskDecision(
                False,
                f"order notional {notional:.2f} exceeds cap {self.settings.max_order_notional:.2f}",
            )

        return RiskDecision(True, f"validated {symbol} for notional {notional:.2f}")
