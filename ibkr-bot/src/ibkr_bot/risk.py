from __future__ import annotations

from dataclasses import dataclass

from ibkr_bot.config import Settings
from ibkr_bot.models import OrderIntent, OrderType, RiskDecision, RiskState, Side


@dataclass(frozen=True)
class RiskManager:
    settings: Settings

    def evaluate(self, intent: OrderIntent, state: RiskState) -> RiskDecision:
        reasons: list[str] = []

        if intent.quantity <= 0:
            reasons.append("quantity must be positive")

        if intent.order_type == OrderType.MARKET and not self.settings.allow_market_orders:
            reasons.append("market orders are disabled")

        if intent.order_type == OrderType.LIMIT and intent.limit_price is None:
            reasons.append("limit orders require a limit_price")

        if intent.estimated_notional > self.settings.max_notional_per_order:
            reasons.append(
                f"order notional {intent.estimated_notional:.2f} exceeds "
                f"max_notional_per_order {self.settings.max_notional_per_order:.2f}"
            )

        if state.orders_today >= self.settings.max_orders_per_day:
            reasons.append(
                f"orders_today {state.orders_today} exceeds or equals "
                f"max_orders_per_day {self.settings.max_orders_per_day}"
            )

        if state.realized_pnl_today <= -abs(self.settings.max_daily_loss):
            reasons.append(
                f"daily realized pnl {state.realized_pnl_today:.2f} breaches "
                f"max_daily_loss {self.settings.max_daily_loss:.2f}"
            )

        current_position = state.positions.get(intent.contract.symbol)
        current_qty = current_position.quantity if current_position else 0.0
        reference_price = intent.limit_price or (current_position.market_price if current_position else 0.0)
        signed_order_qty = intent.quantity if intent.side == Side.BUY else -intent.quantity
        projected_notional = abs((current_qty + signed_order_qty) * reference_price)
        if projected_notional > self.settings.max_position_notional:
            reasons.append(
                f"projected position notional {projected_notional:.2f} exceeds "
                f"max_position_notional {self.settings.max_position_notional:.2f}"
            )

        if self.settings.trading_mode == "live" and not self.settings.allow_live:
            reasons.append("live trading mode requested but IBKR_ALLOW_LIVE is false")

        return RiskDecision(accepted=not reasons, reasons=tuple(reasons))

