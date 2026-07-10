from __future__ import annotations

import unittest

from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import TradeRequest
from ibkr_quant_bot.risk import RiskManager


class RiskManagerTest(unittest.TestCase):
    def test_reduce_only_sell_skips_notional_cap_when_covered(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",), max_order_notional=1.0)
        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="SELL", quantity=10, reduce_only=True),
            reference_price=100.0,
            position_quantity=10,
        )

        self.assertTrue(decision.allowed)

    def test_sell_without_reduce_only_is_rejected(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",))

        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="SELL", quantity=1),
            reference_price=100.0,
            position_quantity=1,
        )

        self.assertFalse(decision.allowed)
        self.assertIn("reduce_only", decision.reason)

    def test_sell_cannot_exceed_position_less_pending_sells(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",))

        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="SELL", quantity=3, reduce_only=True),
            reference_price=100.0,
            position_quantity=5,
            pending_sell_quantity=3,
        )

        self.assertFalse(decision.allowed)
        self.assertIn("available long position 2", decision.reason)

    def test_buy_orders_still_respect_notional_cap(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",), max_order_notional=50.0)
        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="BUY", quantity=1),
            reference_price=100.0,
        )

        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
