from __future__ import annotations

import unittest

from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import TradeRequest
from ibkr_quant_bot.risk import RiskManager


class RiskManagerTest(unittest.TestCase):
    def test_sell_orders_skip_notional_cap(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",), max_order_notional=1.0)
        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="SELL", quantity=10),
            reference_price=100.0,
        )

        self.assertTrue(decision.allowed)

    def test_buy_orders_still_respect_notional_cap(self) -> None:
        settings = Settings(allowed_symbols=("SOXL",), max_order_notional=50.0)
        decision = RiskManager(settings).validate(
            TradeRequest(symbol="SOXL", action="BUY", quantity=1),
            reference_price=100.0,
        )

        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
