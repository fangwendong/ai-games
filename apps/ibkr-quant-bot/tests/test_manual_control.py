from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from ibkr_quant_bot.cli import _activate_detected_manual_pauses, _submit_or_print
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.manual_control import (
    load_manual_strategy_pauses,
    pause_manual_strategy_symbol,
    resume_manual_strategy_symbol,
)
from ibkr_quant_bot.models import TradeRequest


class ManualControlTest(unittest.TestCase):
    def test_pause_persists_until_explicit_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(state_dir=temp_dir)
            pause_manual_strategy_symbol(
                settings,
                "soxs",
                reason="manual BUY order submitted",
                order_ref="manual-1",
            )
            pauses = load_manual_strategy_pauses(settings)
            self.assertEqual(["SOXS"], sorted(pauses))
            self.assertEqual("manual-1", pauses["SOXS"]["order_ref"])
            resume_manual_strategy_symbol(settings, "SOXS")
            self.assertEqual({}, load_manual_strategy_pauses(settings))

    def test_manual_order_pauses_before_live_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                state_dir=temp_dir,
                readonly=False,
                dry_run=False,
                trading_mode="live",
            )

            class Broker:
                def place_order(inner_self, request):
                    self.assertIn("SOXS", load_manual_strategy_pauses(settings))
                    return SimpleNamespace()

            request = TradeRequest(
                symbol="SOXS",
                action="BUY",
                quantity=10,
                order_ref="manual-1",
            )
            with patch("ibkr_quant_bot.cli._record_order_state"):
                result = _submit_or_print(Broker(), settings, request, "allowed")
            self.assertIsNotNone(result)

    def test_strategy_order_is_blocked_after_manual_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                state_dir=temp_dir,
                readonly=False,
                dry_run=False,
                trading_mode="live",
            )
            pause_manual_strategy_symbol(
                settings, "SOXS", reason="manual position detected"
            )
            broker = SimpleNamespace(place_order=lambda request: self.fail("submitted"))
            request = TradeRequest(
                symbol="SOXL",
                action="BUY",
                quantity=10,
                order_ref="momentum-2026-08-06-SOXL-entry-120000",
            )
            result = _submit_or_print(broker, settings, request, "allowed")
            self.assertIsNone(result)

    def test_unowned_position_activates_manual_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(state_dir=temp_dir, trading_mode="live")
            broker = SimpleNamespace(active_trades=lambda: [])
            strategy = SimpleNamespace(symbols=("SOXL", "SOXS"))
            pauses = _activate_detected_manual_pauses(
                broker,
                settings,
                strategy,
                {"SOXS": {"position": "100", "avgCost": "45.0"}},
                datetime(2026, 8, 6),
            )
            self.assertIn("SOXS", pauses)


if __name__ == "__main__":
    unittest.main()
