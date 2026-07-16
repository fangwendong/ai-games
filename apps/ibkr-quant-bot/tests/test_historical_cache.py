from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ibkr_quant_bot.historical_cache import (
    load_bars,
    load_market_data_source,
    require_market_data_source,
    save_bars_by_day,
)
from ibkr_quant_bot.models import Bar


class HistoricalCacheTest(unittest.TestCase):
    def test_records_and_requires_one_market_data_source(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bar = Bar(
                time=datetime(2026, 7, 9, 13, 30, tzinfo=timezone.utc),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )

            save_bars_by_day(root, "SOXL", "5 mins", [bar], exchange="ARCA")

            self.assertEqual("ARCA", load_market_data_source(root))
            self.assertEqual("ARCA", require_market_data_source(root, "ARCA"))
            with self.assertRaisesRegex(ValueError, "expected SMART, found ARCA"):
                require_market_data_source(root, "SMART")
            with self.assertRaisesRegex(ValueError, "cannot write SMART"):
                save_bars_by_day(root, "QQQ", "5 mins", [bar], exchange="SMART")

    def test_rejects_cache_without_source_metadata(self) -> None:
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "has no source metadata"):
                require_market_data_source(temporary, "SMART")

    def test_saves_one_file_per_session_day_and_merges_overlaps(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = Bar(
                time=datetime(2026, 7, 9, 13, 30, tzinfo=timezone.utc),
                open=10,
                high=11,
                low=9,
                close=10.5,
                volume=100,
            )
            replacement = Bar(
                time=first.time,
                open=10,
                high=12,
                low=9,
                close=11.5,
                volume=200,
            )
            second = Bar(
                time=datetime(2026, 7, 10, 13, 30, tzinfo=timezone.utc),
                open=12,
                high=13,
                low=11,
                close=12.5,
                volume=300,
            )

            save_bars_by_day(root, "SOXL", "5 mins", [first, second])
            save_bars_by_day(root, "SOXL", "5 mins", [replacement])

            self.assertTrue((root / "2026-07-09" / "SOXL__5_mins.json").exists())
            self.assertTrue((root / "2026-07-10" / "SOXL__5_mins.json").exists())
            loaded = load_bars(root, "SOXL", "5 mins")
            self.assertEqual(2, len(loaded))
            self.assertEqual(11.5, loaded[0].close)

    def test_duration_filter_excludes_older_days(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = Bar(
                time=datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
            recent = Bar(
                time=datetime(2026, 7, 9, 13, 30, tzinfo=timezone.utc),
                open=2,
                high=2,
                low=2,
                close=2,
                volume=2,
            )
            save_bars_by_day(root, "QQQ", "5 mins", [old, recent])

            loaded = load_bars(
                root,
                "QQQ",
                "5 mins",
                duration="3 D",
                end_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )

            self.assertEqual([2], [bar.close for bar in loaded])

    def test_daily_file_contains_metadata(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bar = Bar(
                time=datetime(2026, 7, 9, 13, 30, tzinfo=timezone.utc),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
            save_bars_by_day(root, "SOXS", "5 mins", [bar])

            path = root / "2026-07-09" / "SOXS__5_mins.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("SOXS", payload["symbol"])
            self.assertEqual("5 mins", payload["bar_size"])
            self.assertEqual(1, payload["schema_version"])
