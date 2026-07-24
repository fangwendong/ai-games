from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ibkr_quant_bot.trade_record import append_trade_record


class TradeRecordTest(unittest.TestCase):
    def test_appends_day_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "state"
            state_dir.mkdir()
            output_path = root / "trade.json"

            (state_dir / "entries-2026-07-23.json").write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "average_fill_price": 160.35,
                                "filled_quantity": 62.0,
                                "quantity": 62,
                                "symbol": "SOXL",
                                "time": "2026-07-23T12:40:05.541232-04:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (state_dir / "orders-2026-07-23.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "recorded_at": "2026-07-23T12:40:05.541232-04:00",
                                "request": {
                                    "action": "BUY",
                                    "reduce_only": False,
                                    "symbol": "SOXL",
                                },
                                "status": {
                                    "avg_fill_price": 160.35,
                                    "filled": 62.0,
                                    "lifecycle": "filled",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "recorded_at": "2026-07-23T13:10:05.541232-04:00",
                                "request": {
                                    "action": "SELL",
                                    "order_ref": "momentum-2026-07-23-SOXL-exit",
                                    "reduce_only": True,
                                    "symbol": "SOXL",
                                },
                                "status": {
                                    "avg_fill_price": 156.6005,
                                    "filled": 62.0,
                                    "lifecycle": "filled",
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            result = append_trade_record(
                state_dir=state_dir,
                output_path=output_path,
                session_date="2026-07-23",
            )

            self.assertTrue(result.appended)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("2026-07-23", payload["days"][0]["date"])
            self.assertEqual(2, len(payload["days"][0]["trades"]))
            self.assertEqual("buy", payload["days"][0]["trades"][0]["side"])
            self.assertEqual("sell", payload["days"][0]["trades"][1]["side"])

            repeat = append_trade_record(
                state_dir=state_dir,
                output_path=output_path,
                session_date="2026-07-23",
            )
            self.assertFalse(repeat.appended)
            payload_again = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(payload_again["days"]))

