from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ibkr_quant_bot.cli import _strategy_runtime_lock_path, main
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.runtime_lock import (
    RuntimeLockError,
    acquire_cache_writer_lock,
    acquire_runtime_lock,
)


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

    def test_only_one_strategy_run_can_hold_runtime_lock(self) -> None:
        with TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "intraday-momentum.run.lock"
            first = acquire_runtime_lock(lock_path)
            try:
                with self.assertRaisesRegex(RuntimeLockError, "already owns"):
                    acquire_runtime_lock(lock_path)
            finally:
                first.close()

            replacement = acquire_runtime_lock(lock_path)
            replacement.close()

    def test_overlapping_intraday_command_skips_before_broker_connection(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = Settings(state_dir=temporary)
            lock_path = _strategy_runtime_lock_path(
                settings, "rotation-hysteresis-v2"
            )
            self.assertEqual(
                lock_path,
                _strategy_runtime_lock_path(settings, "rotation-hysteresis-v1"),
            )
            first = acquire_runtime_lock(lock_path)
            try:
                output = StringIO()
                with (
                    patch("ibkr_quant_bot.cli.load_settings", return_value=settings),
                    patch("ibkr_quant_bot.cli._with_broker") as connect,
                    redirect_stdout(output),
                ):
                    result = main(
                        [
                            "intraday-momentum",
                            "--profile",
                            "rotation-hysteresis-v2",
                        ]
                    )
            finally:
                first.close()

        self.assertEqual(0, result)
        self.assertIn("another rotation-hysteresis-v2 run is active", output.getvalue())
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
