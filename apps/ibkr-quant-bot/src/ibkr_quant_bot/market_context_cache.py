from __future__ import annotations

import json
import math
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .models import Bar, MarketSession


class MarketContextCacheError(RuntimeError):
    pass


def write_market_context_cache(
    path: str | Path,
    *,
    session_date: date,
    session: MarketSession | None,
    bars_by_symbol: dict[str, list[Bar]],
    source: str,
    bar_size: str,
    generated_at: datetime | None = None,
) -> None:
    cache_path = Path(path).expanduser()
    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    generated = generated.astimezone(timezone.utc)
    payload = {
        "version": 1,
        "source": source.upper(),
        "bar_size": bar_size,
        "generated_at": generated.isoformat(),
        "session_date": session_date.isoformat(),
        "session": None
        if session is None
        else {
            "opens_at": session.opens_at.isoformat(),
            "closes_at": session.closes_at.isoformat(),
        },
        "symbols": {
            symbol.upper(): [
                {
                    "time": bar.time.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ]
            for symbol, bars in bars_by_symbol.items()
        },
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(
        f".{cache_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("w") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, cache_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_cached_market_session(
    path: str | Path,
    *,
    session_date: date,
    max_age_seconds: float,
    now: datetime | None = None,
) -> MarketSession | None:
    payload = _load_payload(
        path,
        session_date=session_date,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    raw = payload.get("session")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MarketContextCacheError("market context cache has invalid session")
    try:
        opens_at = datetime.fromisoformat(str(raw["opens_at"]))
        closes_at = datetime.fromisoformat(str(raw["closes_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketContextCacheError(
            "market context cache has invalid session timestamps"
        ) from exc
    if opens_at.tzinfo is None or closes_at.tzinfo is None or closes_at <= opens_at:
        raise MarketContextCacheError("market context cache has unusable session")
    return MarketSession(session_date, opens_at, closes_at)


def load_fresh_cached_bars(
    path: str | Path,
    symbols: tuple[str, ...],
    *,
    session_date: date,
    source: str,
    bar_size: str,
    max_age_seconds: float,
    now: datetime | None = None,
) -> dict[str, list[Bar]]:
    payload = _load_payload(
        path,
        session_date=session_date,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    if str(payload.get("source", "")).upper() != source.upper():
        raise MarketContextCacheError("market context cache source mismatch")
    if payload.get("bar_size") != bar_size:
        raise MarketContextCacheError("market context cache bar-size mismatch")
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, dict):
        raise MarketContextCacheError("market context cache has invalid symbols")
    result: dict[str, list[Bar]] = {}
    for raw_symbol in symbols:
        symbol = raw_symbol.upper()
        rows = raw_symbols.get(symbol)
        if not isinstance(rows, list) or not rows:
            raise MarketContextCacheError(f"market context cache missing {symbol}")
        result[symbol] = [_decode_bar(symbol, row) for row in rows]
    return result


def _load_payload(
    path: str | Path,
    *,
    session_date: date,
    max_age_seconds: float,
    now: datetime | None,
) -> dict[str, object]:
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    cache_path = Path(path).expanduser()
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketContextCacheError(
            f"market context cache unavailable: {cache_path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise MarketContextCacheError("market context cache has invalid metadata")
    if payload.get("session_date") != session_date.isoformat():
        raise MarketContextCacheError("market context cache session-date mismatch")
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketContextCacheError(
            "market context cache has invalid generated_at"
        ) from exc
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (
        current.astimezone(timezone.utc) - generated_at.astimezone(timezone.utc)
    ).total_seconds()
    if age < -1 or age > max_age_seconds:
        raise MarketContextCacheError("market context cache is stale")
    return payload


def _decode_bar(symbol: str, row: object) -> Bar:
    if not isinstance(row, dict):
        raise MarketContextCacheError(
            f"market context cache has invalid {symbol} bar"
        )
    try:
        timestamp = datetime.fromisoformat(str(row["time"]))
        values = [
            float(row[name]) for name in ("open", "high", "low", "close", "volume")
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketContextCacheError(
            f"market context cache has invalid {symbol} bar"
        ) from exc
    if timestamp.tzinfo is None or not all(math.isfinite(value) for value in values):
        raise MarketContextCacheError(
            f"market context cache has unusable {symbol} bar"
        )
    return Bar(timestamp, *values)
