from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from ibkr_quant_bot.history_refresh import (
    expected_session_timestamps,
    validate_recent_cached_sessions,
)
from ibkr_quant_bot.models import Bar, MarketSession


def bars_for(session: MarketSession) -> list[Bar]:
    return [
        Bar(timestamp, 1, 1, 1, 1, 1)
        for timestamp in expected_session_timestamps(session)
    ]


class HistoryRefreshTest(unittest.TestCase):
    def test_expected_timestamps_follow_early_close_schedule(self) -> None:
        session = MarketSession(
            session_date=date(2026, 11, 27),
            opens_at=datetime(2026, 11, 27, 9, 30, tzinfo=timezone.utc),
            closes_at=datetime(2026, 11, 27, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(42, len(expected_session_timestamps(session)))

    def test_validation_requires_latest_completed_scheduled_sessions(self) -> None:
        first = MarketSession(
            session_date=date(2026, 7, 13),
            opens_at=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
            closes_at=datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc),
        )
        second = MarketSession(
            session_date=date(2026, 7, 14),
            opens_at=datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc),
            closes_at=datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc),
        )
        sessions = {first.session_date: first, second.session_date: second}
        bars = bars_for(first) + bars_for(second)

        report = validate_recent_cached_sessions(
            {symbol: bars for symbol in ("SOXL", "SOXS", "QQQ")},
            sessions,
            now=second.closes_at + timedelta(hours=1),
        )

        self.assertEqual("2026-07-14", report["latest_completed_session"])
        self.assertEqual(78, report["counts"]["2026-07-14"]["SOXS"])

    def test_validation_fails_when_latest_cached_session_is_missing(self) -> None:
        session = MarketSession(
            session_date=date(2026, 7, 14),
            opens_at=datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc),
            closes_at=datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc),
        )
        incomplete = bars_for(session)[:-1]

        with self.assertRaisesRegex(ValueError, "timeline mismatch"):
            validate_recent_cached_sessions(
                {
                    "SOXL": bars_for(session),
                    "SOXS": incomplete,
                    "QQQ": bars_for(session),
                },
                {session.session_date: session},
                now=session.closes_at + timedelta(hours=1),
                recent_sessions=1,
            )


if __name__ == "__main__":
    unittest.main()
