from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ibkr_quant_bot.live_review_log import append_review_log


class LiveReviewLogTest(unittest.TestCase):
    def test_appends_session_block_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "state"
            state_dir.mkdir()
            doc_path = root / "live-strategy-review-log.md"

            doc_path.write_text(
                "# Live Strategy Review Log\n\n## Follow-Up Items\n",
                encoding="utf-8",
            )

            (state_dir / "entries-2026-07-17.json").write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "average_fill_price": 138.88,
                                "filled_quantity": 21.0,
                                "limit_price": 139.21,
                                "order_ref": "momentum-2026-07-17-SOXL-entry-120004",
                                "order_type": "LMT",
                                "protective_stop_price": 133.35142857142856,
                                "protective_take_price": 144.088,
                                "quantity": 21,
                                "reduce_only": False,
                                "strategy_version": "rotation-hysteresis-v2",
                                "symbol": "SOXL",
                                "time": "2026-07-17T12:00:06.602591-04:00",
                                "time_in_force": "DAY",
                            }
                        ],
                        "entry_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            (state_dir / "orders-2026-07-17.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "fills": [],
                                "log": [],
                                "order": {"action": "BUY"},
                                "recorded_at": "2026-07-17T12:00:05.339114-04:00",
                                "request": {
                                    "action": "BUY",
                                    "reduce_only": False,
                                    "symbol": "SOXL",
                                },
                                "status": {
                                    "avg_fill_price": 138.88,
                                    "filled": 21.0,
                                    "lifecycle": "filled",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "fills": [],
                                "log": [],
                                "order": {"action": "SELL"},
                                "recorded_at": "2026-07-17T12:00:06.602170-04:00",
                                "request": {
                                    "action": "SELL",
                                    "reduce_only": True,
                                    "symbol": "SOXL",
                                },
                                "status": {
                                    "avg_fill_price": 0.0,
                                    "filled": 0.0,
                                    "lifecycle": "active",
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            (state_dir / "market-data-source-2026-07-17.json").write_text(
                json.dumps(
                    {
                        "bar_exchange": "SMART",
                        "quote_exchange": "SMART",
                        "reason": "all strategy symbols passed SMART validation",
                    }
                ),
                encoding="utf-8",
            )

            result = append_review_log(
                state_dir=state_dir,
                doc_path=doc_path,
                session_date="2026-07-17",
            )

            self.assertTrue(result.appended)
            text = doc_path.read_text(encoding="utf-8")
            self.assertIn("## 2026-07-17", text)
            self.assertIn("Entry time, symbol, quantity, average fill, and reason:", text)
            self.assertIn("Exit time, quantity, average fill, and reason: N/A", text)

            repeat = append_review_log(
                state_dir=state_dir,
                doc_path=doc_path,
                session_date="2026-07-17",
            )
            self.assertFalse(repeat.appended)

    def test_no_trade_session_uses_latest_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "state"
            state_dir.mkdir()
            doc_path = root / "live-strategy-review-log.md"
            summary_path = root / "latest-summary.txt"

            doc_path.write_text(
                "# Live Strategy Review Log\n\n## Follow-Up Items\n",
                encoding="utf-8",
            )
            summary_path.write_text("🟢 V2 实盘轮询｜退出码 0\n本轮结论：未下单｜无额外执行信息", encoding="utf-8")

            result = append_review_log(
                state_dir=state_dir,
                doc_path=doc_path,
                session_date="2026-07-18",
                latest_summary_path=summary_path,
            )

            self.assertTrue(result.appended)
            text = doc_path.read_text(encoding="utf-8")
            self.assertIn("No filled entry was recorded", text)
            self.assertIn("Latest live summary", text)


if __name__ == "__main__":
    unittest.main()
