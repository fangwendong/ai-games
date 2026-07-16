from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ibkr_quant_bot.runtime_lock import RuntimeLockError, acquire_cache_writer_lock


class RuntimeLockTest(unittest.TestCase):
    def test_only_one_writer_can_hold_cache_lock(self) -> None:
        with TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache.json"
            first = acquire_cache_writer_lock(cache)
            try:
                with self.assertRaisesRegex(RuntimeLockError, "already owns"):
                    acquire_cache_writer_lock(cache)
            finally:
                first.close()

            replacement = acquire_cache_writer_lock(cache)
            replacement.close()


if __name__ == "__main__":
    unittest.main()
