from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import Bar

SCHEMA_VERSION = 1
SOURCE_METADATA_FILENAME = "market-data-source.json"
SUPPORTED_EXCHANGES = {"SMART", "ARCA"}


def _normalize_exchange(exchange: str) -> str:
    normalized = exchange.upper()
    if normalized not in SUPPORTED_EXCHANGES:
        raise ValueError(f"unsupported market-data exchange: {exchange}")
    return normalized


def load_market_data_source(data_dir: str | Path) -> str | None:
    path = Path(data_dir) / SOURCE_METADATA_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_exchange(str(payload["exchange"]))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid historical market-data source metadata: {path}") from exc


def record_market_data_source(data_dir: str | Path, exchange: str) -> str:
    root = Path(data_dir)
    normalized = _normalize_exchange(exchange)
    existing = load_market_data_source(root)
    if existing is not None and existing != normalized:
        raise ValueError(
            f"historical cache source mismatch: {root} is {existing}, "
            f"cannot write {normalized} data"
        )
    path = root / SOURCE_METADATA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "exchange": normalized},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return normalized


def require_market_data_source(data_dir: str | Path, exchange: str) -> str:
    normalized = _normalize_exchange(exchange)
    actual = load_market_data_source(data_dir)
    if actual is None:
        raise ValueError(
            f"historical cache has no source metadata: "
            f"{Path(data_dir) / SOURCE_METADATA_FILENAME}"
        )
    if actual != normalized:
        raise ValueError(
            f"historical cache source mismatch: expected {normalized}, found {actual}"
        )
    return actual


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _filename(symbol: str, bar_size: str) -> str:
    return f"{symbol.upper()}__{bar_size.replace(' ', '_')}.json"


def _bar_payload(bar: Bar) -> dict[str, object]:
    return {
        "time": _utc(bar.time).isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _bar_from_payload(payload: dict[str, object]) -> Bar:
    return Bar(
        time=datetime.fromisoformat(str(payload["time"])),
        open=float(payload["open"]),
        high=float(payload["high"]),
        low=float(payload["low"]),
        close=float(payload["close"]),
        volume=float(payload["volume"]),
    )


def save_bars_by_day(
    data_dir: str | Path,
    symbol: str,
    bar_size: str,
    bars: list[Bar],
    *,
    exchange: str | None = None,
) -> None:
    root = Path(data_dir)
    if exchange is not None:
        record_market_data_source(root, exchange)
    grouped: dict[date, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(_utc(bar.time).date(), []).append(bar)
    for session_day, day_bars in grouped.items():
        path = root / session_day.isoformat() / _filename(symbol, bar_size)
        existing = load_bars(root, symbol, bar_size, session_day=session_day)
        by_time = {_utc(bar.time): bar for bar in existing}
        by_time.update({_utc(bar.time): bar for bar in day_bars})
        payload = {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "bar_size": bar_size,
            "bars": [_bar_payload(by_time[key]) for key in sorted(by_time)],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_bars(
    data_dir: str | Path,
    symbol: str,
    bar_size: str,
    *,
    duration: str | None = None,
    end_time: datetime | None = None,
    session_day: date | None = None,
) -> list[Bar]:
    root = Path(data_dir)
    paths = []
    if session_day is not None:
        paths = [root / session_day.isoformat() / _filename(symbol, bar_size)]
    elif root.exists():
        paths = sorted(root.glob(f"*/{_filename(symbol, bar_size)}"))
    bars: list[Bar] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            bars.extend(_bar_from_payload(item) for item in payload.get("bars", []))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    deduped = {_utc(bar.time): bar for bar in bars}
    result = [deduped[key] for key in sorted(deduped)]
    if duration and result:
        end = _utc(end_time or datetime.now(timezone.utc))
        parts = duration.upper().split()
        value, unit = int(parts[0]), parts[1].rstrip("S")
        days = value * {"D": 1, "W": 7, "M": 30, "Y": 365}[unit]
        start = end - timedelta(days=days)
        result = [bar for bar in result if start <= _utc(bar.time) <= end]
    return result
