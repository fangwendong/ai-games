from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from zoneinfo import ZoneInfo

from ibkr_quant_bot.market_context_cache import (
    MarketContextCacheError,
    load_cached_market_session,
    load_fresh_cached_bars,
    write_market_context_cache,
)
from ibkr_quant_bot.models import Bar, MarketSession


NEW_YORK = ZoneInfo("America/New_York")


class MarketContextCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 17, 12, 1, tzinfo=NEW_YORK)
        self.session = MarketSession(
            date(2026, 7, 17),
            datetime(2026, 7, 17, 9, 30, tzinfo=NEW_YORK),
            datetime(2026, 7, 17, 16, 0, tzinfo=NEW_YORK),
        )
        self.bars = {
            symbol: [
                Bar(
                    datetime(2026, 7, 17, 11, 55, tzinfo=NEW_YORK),
                    10.0,
                    10.2,
                    9.9,
                    10.1,
                    100.0,
                )
            ]
            for symbol in ("QQQ", "SOXL", "SOXS")
        }

    def test_round_trip_complete_context(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            write_market_context_cache(
                path,
                session_date=self.session.session_date,
                session=self.session,
                bars_by_symbol=self.bars,
                source="SMART",
                bar_size="5 mins",
                generated_at=self.now.astimezone(timezone.utc),
            )

            session = load_cached_market_session(
                path,
                session_date=self.session.session_date,
                max_age_seconds=420,
                now=self.now,
            )
            loaded = load_fresh_cached_bars(
                path,
                tuple(self.bars),
                session_date=self.session.session_date,
                source="SMART",
                bar_size="5 mins",
                max_age_seconds=420,
                now=self.now,
            )

            self.assertEqual(self.session, session)
            self.assertEqual(self.bars, loaded)

    def test_rejects_stale_or_incomplete_group(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            write_market_context_cache(
                path,
                session_date=self.session.session_date,
                session=self.session,
                bars_by_symbol={"QQQ": self.bars["QQQ"]},
                source="SMART",
                bar_size="5 mins",
                generated_at=self.now.astimezone(timezone.utc) - timedelta(minutes=8),
            )
            with self.assertRaisesRegex(MarketContextCacheError, "stale"):
                load_fresh_cached_bars(
                    path,
                    tuple(self.bars),
                    session_date=self.session.session_date,
                    source="SMART",
                    bar_size="5 mins",
                    max_age_seconds=420,
                    now=self.now,
                )

            payload = json.loads(path.read_text())
            payload["generated_at"] = self.now.astimezone(timezone.utc).isoformat()
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MarketContextCacheError, "missing SOXL"):
                load_fresh_cached_bars(
                    path,
                    tuple(self.bars),
                    session_date=self.session.session_date,
                    source="SMART",
                    bar_size="5 mins",
                    max_age_seconds=420,
                    now=self.now,
                )

    def test_explicit_holiday_round_trip(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            write_market_context_cache(
                path,
                session_date=self.session.session_date,
                session=None,
                bars_by_symbol={},
                source="SMART",
                bar_size="5 mins",
                generated_at=self.now.astimezone(timezone.utc),
            )
            self.assertIsNone(
                load_cached_market_session(
                    path,
                    session_date=self.session.session_date,
                    max_age_seconds=420,
                    now=self.now,
                )
            )


if __name__ == "__main__":
    unittest.main()
