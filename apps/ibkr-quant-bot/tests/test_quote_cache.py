from __future__ import annotations

import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ibkr_quant_bot.models import Quote
from ibkr_quant_bot.quote_cache import (
    QuoteCacheError,
    QuoteCacheWriter,
    load_fresh_quotes,
)


class QuoteCacheTest(unittest.TestCase):
    def test_writer_caps_each_symbol_and_atomically_replaces_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live-quotes.json"
            writer = QuoteCacheWriter(
                path,
                ("QQQ", "SOXL", "SOXS"),
                max_samples_per_symbol=3,
            )
            for index in range(10):
                writer.update(
                    {
                        symbol: Quote(
                            symbol,
                            bid=10 + index,
                            ask=10.1 + index,
                            last=10.05 + index,
                            close=10.0,
                        )
                        for symbol in ("QQQ", "SOXL", "SOXS")
                    },
                    market_times={
                        symbol: datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
                        for symbol in ("QQQ", "SOXL", "SOXS")
                    },
                    received_times={
                        symbol: datetime(
                            2026, 7, 16, 14, 0, 0, 100_000, tzinfo=timezone.utc
                        )
                        for symbol in ("QQQ", "SOXL", "SOXS")
                    },
                    monotonic_now=float(index) / 10,
                    force=index == 9,
                )

            payload = json.loads(path.read_text())
            self.assertEqual(3, payload["max_samples_per_symbol"])
            self.assertTrue(
                all(len(rows) == 3 for rows in payload["symbols"].values())
            )
            self.assertTrue(
                all(
                    rows[-1]["received_at"].startswith(
                        "2026-07-16T14:00:00.100000"
                    )
                    for rows in payload["symbols"].values()
                )
            )
            self.assertTrue(
                all(rows[-1]["published_at"] for rows in payload["symbols"].values())
            )
            self.assertTrue(
                all(
                    rows[-1]["market_time"].startswith("2026-07-16T14:00:00")
                    for rows in payload["symbols"].values()
                )
            )
            self.assertEqual([], list(path.parent.glob(".*.tmp")))

    def test_writer_refreshes_no_more_than_once_per_interval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            writer = QuoteCacheWriter(
                Path(tmpdir) / "live-quotes.json",
                ("QQQ",),
                refresh_seconds=1.0,
            )
            quote = {"QQQ": Quote("QQQ", 10.0, 10.1, 10.05, 10.0)}

            self.assertTrue(writer.update(quote, monotonic_now=0.0))
            self.assertFalse(writer.update({}, monotonic_now=0.5))
            self.assertTrue(writer.update({}, monotonic_now=1.0))

    def test_reader_returns_complete_fresh_group(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live-quotes.json"
            symbols = ("QQQ", "SOXL", "SOXS")
            now = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
            writer = QuoteCacheWriter(path, symbols)
            writer.update(
                {
                    symbol: Quote(symbol, 10.0, 10.1, 10.05, 10.0)
                    for symbol in symbols
                },
                observed_at=now,
                force=True,
            )

            quotes = load_fresh_quotes(
                path, symbols, max_age_seconds=3.0, now=now + timedelta(seconds=2)
            )

            self.assertEqual(set(symbols), set(quotes))

    def test_reader_rejects_stale_or_incomplete_group(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live-quotes.json"
            now = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
            writer = QuoteCacheWriter(path, ("QQQ", "SOXL"))
            writer.update(
                {
                    symbol: Quote(symbol, 10.0, 10.1, 10.05, 10.0)
                    for symbol in ("QQQ", "SOXL")
                },
                observed_at=now,
                force=True,
            )

            with self.assertRaisesRegex(QuoteCacheError, "stale"):
                load_fresh_quotes(
                    path,
                    ("QQQ", "SOXL"),
                    max_age_seconds=3.0,
                    now=now + timedelta(seconds=4),
                )
            with self.assertRaisesRegex(QuoteCacheError, "missing SOXS"):
                load_fresh_quotes(
                    path,
                    ("QQQ", "SOXL", "SOXS"),
                    max_age_seconds=3.0,
                    now=now,
                )

    def test_reader_rejects_corrupt_metadata_future_and_invalid_prices(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live-quotes.json"
            symbols = ("QQQ", "SOXL", "SOXS")
            now = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
            path.write_text('{"version":')
            with self.assertRaisesRegex(QuoteCacheError, "unavailable"):
                load_fresh_quotes(path, symbols, max_age_seconds=3, now=now)

            writer = QuoteCacheWriter(path, symbols)
            writer.update(
                {
                    symbol: Quote(symbol, 10.0, 10.1, 10.05, 10.0)
                    for symbol in symbols
                },
                observed_at=now + timedelta(seconds=2),
                force=True,
            )
            with self.assertRaisesRegex(QuoteCacheError, "stale"):
                load_fresh_quotes(path, symbols, max_age_seconds=3, now=now)

            payload = json.loads(path.read_text())
            payload["symbols"]["SOXL"][-1].update(
                {"bid": "not-a-number", "ask": None, "last": None}
            )
            for rows in payload["symbols"].values():
                rows[-1]["observed_at"] = now.isoformat()
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(QuoteCacheError, "non-numeric"):
                load_fresh_quotes(path, symbols, max_age_seconds=3, now=now)

            payload["source"] = "ARCA"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(QuoteCacheError, "invalid metadata"):
                load_fresh_quotes(path, symbols, max_age_seconds=3, now=now)

    def test_atomic_replacement_never_exposes_partial_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live-quotes.json"
            symbols = ("QQQ", "SOXL", "SOXS")
            writer = QuoteCacheWriter(path, symbols, max_samples_per_symbol=100)
            errors: list[Exception] = []

            def publish() -> None:
                for index in range(300):
                    writer.update(
                        {
                            symbol: Quote(symbol, 10, 10.1, 10.05, 10)
                            for symbol in symbols
                        },
                        monotonic_now=float(index),
                        force=True,
                    )

            worker = threading.Thread(target=publish)
            worker.start()
            while worker.is_alive():
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text())
                    self.assertEqual(1, payload["version"])
                    self.assertTrue(
                        all(len(rows) <= 100 for rows in payload["symbols"].values())
                    )
                except Exception as exc:  # pragma: no cover - assertion captured below
                    errors.append(exc)
                    break
            worker.join()
            self.assertEqual([], errors)
            self.assertEqual([], list(path.parent.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
