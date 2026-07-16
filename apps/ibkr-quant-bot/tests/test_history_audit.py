from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ibkr_quant_bot.history_audit import audit_historical_bars
from ibkr_quant_bot.models import Bar


def session(start: datetime, count: int = 78) -> list[Bar]:
    return [
        Bar(
            time=start + timedelta(minutes=5 * index),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1_000,
        )
        for index in range(count)
    ]


class HistoryAuditTest(unittest.TestCase):
    def test_complete_aligned_history_passes(self) -> None:
        first = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        bars = session(first) + session(first + timedelta(days=1))

        report = audit_historical_bars({"AAA": bars, "BBB": bars})

        self.assertEqual("passed", report.status)
        self.assertEqual(2, report.symbols[0].session_count)

    def test_partial_first_boundary_is_reported_but_allowed(self) -> None:
        first = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        bars = session(first, 20) + session(first + timedelta(days=1))

        report = audit_historical_bars({"AAA": bars})

        self.assertEqual("passed", report.status)
        self.assertEqual(1, len(report.symbols[0].boundary_partial_sessions))

    def test_missing_internal_session_fails(self) -> None:
        first = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        all_days = session(first) + session(first + timedelta(days=1)) + session(
            first + timedelta(days=2)
        )
        missing_middle = session(first) + session(first + timedelta(days=2))

        report = audit_historical_bars({"AAA": all_days, "BBB": missing_middle})

        self.assertEqual("failed", report.status)
        self.assertIn("BBB: 1 missing sessions", "\n".join(report.errors))


if __name__ == "__main__":
    unittest.main()
