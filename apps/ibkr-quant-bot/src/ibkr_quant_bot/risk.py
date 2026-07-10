from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .models import RiskDecision, TradeRequest


@dataclass(frozen=True)
class RiskManager:
    settings: Settings

    def validate(self, request: TradeRequest, reference_price: float) -> RiskDecision:
        symbol = request.symbol.upper()
        if request.quantity <= 0:
            return RiskDecision(False, "quantity must be positive")

        if self.settings.is_live and not self.settings.allow_live_trading:
            return RiskDecision(False, "live trading is disabled by IBKR_ALLOW_LIVE_TRADING=false")

        allowed_symbols = {item.upper() for item in self.settings.allowed_symbols}
        if symbol not in allowed_symbols:
            return RiskDecision(False, f"{symbol} is not in IBKR_ALLOWED_SYMBOLS")

        if request.action.upper() == "SELL":
            return RiskDecision(True, f"validated {symbol} sell order")

        notional = reference_price * request.quantity
        if notional > self.settings.max_order_notional:
            return RiskDecision(False, f"order notional {notional:.2f} exceeds cap {self.settings.max_order_notional:.2f}")

        return RiskDecision(True, f"validated {symbol} for notional {notional:.2f}")
