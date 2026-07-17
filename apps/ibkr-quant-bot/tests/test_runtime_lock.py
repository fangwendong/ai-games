from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from ibkr_quant_bot.cli import _strategy_runtime_lock_path, _with_broker, main
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.runtime_lock import (
    RUNTIME_TIMEOUT_EXIT_CODE,
    RuntimeLockError,
    acquire_cache_writer_lock,
    acquire_runtime_lock,
    arm_runtime_lock_deadline,
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

    def test_runtime_deadline_releases_lock_and_hard_exits_process(self) -> None:
        with TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "intraday-momentum.run.lock"
            source_root = Path(__file__).resolve().parents[1] / "src"
            child_code = "\n".join(
                (
                    "import sys, time",
                    "from ibkr_quant_bot.runtime_lock import acquire_runtime_lock, arm_runtime_lock_deadline",
                    "handle = acquire_runtime_lock(sys.argv[1])",
                    "arm_runtime_lock_deadline(handle, 0.05)",
                    "time.sleep(10)",
                )
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(source_root)
            completed = subprocess.run(
                [sys.executable, "-c", child_code, str(lock_path)],
                env=env,
                text=True,
                capture_output=True,
                timeout=2,
                check=False,
            )

            self.assertEqual(RUNTIME_TIMEOUT_EXIT_CODE, completed.returncode)
            self.assertIn("runtime lock released", completed.stderr)
            replacement = acquire_runtime_lock(lock_path)
            replacement.close()

    def test_runtime_deadline_can_be_cancelled(self) -> None:
        with TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "intraday-momentum.run.lock"
            handle = acquire_runtime_lock(lock_path)
            deadline = arm_runtime_lock_deadline(handle, 10)
            deadline.cancel()
            handle.close()

            replacement = acquire_runtime_lock(lock_path)
            replacement.close()

    def test_broker_connect_timeout_disconnects_partial_client(self) -> None:
        broker = MagicMock()
        broker.connect.side_effect = TimeoutError("connect timed out")
        settings = Settings(request_timeout=3.0)

        with (
            patch("ibkr_quant_bot.cli.IbkrBroker", return_value=broker),
            self.assertRaisesRegex(TimeoutError, "connect timed out"),
        ):
            _with_broker(settings)

        broker.disconnect.assert_called_once_with()

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

    def test_intraday_remote_timeout_fails_and_releases_runtime_lock(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = Settings(state_dir=temporary, request_timeout=30.0)
            captured_timeouts: list[float] = []

            def timeout_connect(received: Settings):
                captured_timeouts.append(received.request_timeout)
                raise TimeoutError("remote request timed out")

            error = StringIO()
            with (
                patch("ibkr_quant_bot.cli.load_settings", return_value=settings),
                patch(
                    "ibkr_quant_bot.cli._with_broker", side_effect=timeout_connect
                ),
                redirect_stderr(error),
            ):
                result = main(
                    [
                        "intraday-momentum",
                        "--profile",
                        "rotation-hysteresis-v2",
                    ]
                )

            self.assertEqual(1, result)
            self.assertEqual([3.0], captured_timeouts)
            self.assertIn("intraday momentum failed: TimeoutError", error.getvalue())
            lock_path = _strategy_runtime_lock_path(
                settings, "rotation-hysteresis-v2"
            )
            replacement = acquire_runtime_lock(lock_path)
            replacement.close()


if __name__ == "__main__":
    unittest.main()
