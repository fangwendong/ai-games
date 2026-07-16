from __future__ import annotations

import json
import threading
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
                source="SMART",
                bar_size="5 mins",
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
                    source="SMART",
                    bar_size="5 mins",
                    max_age_seconds=420,
                    now=self.now,
                )
            )

    def test_rejects_wrong_date_source_bar_size_and_future_generation(self) -> None:
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
            cases = (
                ("session_date", "2026-07-16", "session-date mismatch"),
                ("source", "ARCA", "source mismatch"),
                ("bar_size", "1 min", "bar-size mismatch"),
                (
                    "generated_at",
                    (self.now + timedelta(seconds=2)).astimezone(timezone.utc).isoformat(),
                    "stale",
                ),
            )
            original = json.loads(path.read_text())
            for key, value, message in cases:
                with self.subTest(key=key):
                    payload = dict(original)
                    payload[key] = value
                    path.write_text(json.dumps(payload))
                    with self.assertRaisesRegex(MarketContextCacheError, message):
                        load_cached_market_session(
                            path,
                            session_date=self.session.session_date,
                            source="SMART",
                            bar_size="5 mins",
                            max_age_seconds=420,
                            now=self.now,
                        )

    def test_rejects_corrupt_json_and_invalid_ohlcv(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            path.write_text('{"version":')
            with self.assertRaisesRegex(MarketContextCacheError, "unavailable"):
                load_fresh_cached_bars(
                    path,
                    tuple(self.bars),
                    session_date=self.session.session_date,
                    source="SMART",
                    bar_size="5 mins",
                    max_age_seconds=420,
                    now=self.now,
                )

            write_market_context_cache(
                path,
                session_date=self.session.session_date,
                session=self.session,
                bars_by_symbol=self.bars,
                source="SMART",
                bar_size="5 mins",
                generated_at=self.now.astimezone(timezone.utc),
            )
            payload = json.loads(path.read_text())
            payload["symbols"]["SOXL"][0]["high"] = 9.0
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MarketContextCacheError, "unusable SOXL"):
                load_fresh_cached_bars(
                    path,
                    tuple(self.bars),
                    session_date=self.session.session_date,
                    source="SMART",
                    bar_size="5 mins",
                    max_age_seconds=420,
                    now=self.now,
                )

    def test_atomic_replacement_never_exposes_partial_json(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            errors: list[Exception] = []

            def publish() -> None:
                for _ in range(200):
                    write_market_context_cache(
                        path,
                        session_date=self.session.session_date,
                        session=self.session,
                        bars_by_symbol=self.bars,
                        source="SMART",
                        bar_size="5 mins",
                    )

            worker = threading.Thread(target=publish)
            worker.start()
            while worker.is_alive():
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text())
                    self.assertEqual(1, payload["version"])
                except Exception as exc:  # pragma: no cover - assertion captured below
                    errors.append(exc)
                    break
            worker.join()
            self.assertEqual([], errors)
            self.assertEqual([], list(path.parent.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
