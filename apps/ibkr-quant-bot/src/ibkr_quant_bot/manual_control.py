from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
MANUAL_STRATEGY_PAUSE_FILE = "manual-strategy-pauses.json"


def manual_strategy_pause_path(settings: Any) -> Path:
    return Path(settings.state_dir).expanduser() / MANUAL_STRATEGY_PAUSE_FILE


def load_manual_strategy_pauses(settings: Any) -> dict[str, dict[str, object]]:
    path = manual_strategy_pause_path(settings)
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("paused_symbols", {}) if isinstance(payload, dict) else {}
    if not isinstance(rows, dict):
        return {}
    return {
        str(symbol).upper(): dict(detail)
        for symbol, detail in rows.items()
        if isinstance(detail, dict)
    }


def pause_manual_strategy_symbol(
    settings: Any,
    symbol: str,
    *,
    reason: str,
    order_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, object]]:
    symbol = symbol.upper()
    now = now or datetime.now(NEW_YORK)
    pauses = load_manual_strategy_pauses(settings)
    pauses[symbol] = {
        "paused_at": now.isoformat(),
        "reason": reason,
        "order_ref": order_ref,
    }
    _write_state(settings, pauses)
    return pauses


def resume_manual_strategy_symbol(
    settings: Any, symbol: str
) -> dict[str, dict[str, object]]:
    pauses = load_manual_strategy_pauses(settings)
    pauses.pop(symbol.upper(), None)
    _write_state(settings, pauses)
    return pauses


def _write_state(
    settings: Any, pauses: dict[str, dict[str, object]]
) -> None:
    path = manual_strategy_pause_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "paused_symbols": pauses}
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
