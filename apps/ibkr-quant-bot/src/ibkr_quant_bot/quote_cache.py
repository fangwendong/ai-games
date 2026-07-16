from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import Quote


class QuoteCacheError(RuntimeError):
    pass


class QuoteCacheWriter:
    """Maintain a bounded in-memory quote history and atomically publish it."""

    def __init__(
        self,
        path: str | Path,
        symbols: tuple[str, ...],
        *,
        max_samples_per_symbol: int = 100,
        refresh_seconds: float = 1.0,
    ) -> None:
        if not symbols:
            raise ValueError("symbols must not be empty")
        if max_samples_per_symbol <= 0:
            raise ValueError("max_samples_per_symbol must be positive")
        if refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be positive")
        self.path = Path(path).expanduser()
        self.symbols = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
        self.max_samples_per_symbol = max_samples_per_symbol
        self.refresh_seconds = refresh_seconds
        self.samples: dict[str, deque[dict[str, object]]] = {
            symbol: deque(maxlen=max_samples_per_symbol) for symbol in self.symbols
        }
        self._last_flush_monotonic: float | None = None

    def update(
        self,
        quotes: dict[str, Quote],
        *,
        market_times: dict[str, datetime | None] | None = None,
        received_times: dict[str, datetime | None] | None = None,
        observed_at: datetime | None = None,
        monotonic_now: float | None = None,
        force: bool = False,
    ) -> bool:
        observed_at = observed_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        observed_at = observed_at.astimezone(timezone.utc)
        market_times = market_times or {}
        received_times = received_times or {}
        for symbol, quote in quotes.items():
            normalized = symbol.upper()
            if normalized not in self.samples:
                continue
            if quote.bid is None and quote.ask is None and quote.last is None:
                continue
            market_time = market_times.get(normalized)
            if market_time is not None:
                if market_time.tzinfo is None:
                    market_time = market_time.replace(tzinfo=timezone.utc)
                market_time_value = market_time.astimezone(timezone.utc).isoformat()
            else:
                market_time_value = None
            received_time = received_times.get(normalized)
            if received_time is not None:
                if received_time.tzinfo is None:
                    received_time = received_time.replace(tzinfo=timezone.utc)
                received_time_value = received_time.astimezone(timezone.utc).isoformat()
            else:
                received_time_value = None
            self.samples[normalized].append(
                {
                    "market_time": market_time_value,
                    "received_at": received_time_value,
                    "observed_at": observed_at.isoformat(),
                    **asdict(quote),
                    "symbol": normalized,
                }
            )

        now = time.monotonic() if monotonic_now is None else monotonic_now
        should_flush = force or self._last_flush_monotonic is None
        if self._last_flush_monotonic is not None:
            should_flush = should_flush or (
                now - self._last_flush_monotonic >= self.refresh_seconds
            )
        if not should_flush or not any(self.samples.values()):
            return False
        self._write_atomic()
        self._last_flush_monotonic = now
        return True

    def _write_atomic(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.now(timezone.utc)
        payload = {
            "version": 1,
            "source": "SMART",
            "generated_at": generated_at.isoformat(),
            "max_samples_per_symbol": self.max_samples_per_symbol,
            "symbols": {
                symbol: list(self.samples[symbol]) for symbol in self.symbols
            },
        }
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, separators=(",", ":")))
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_fresh_quotes(
    path: str | Path,
    symbols: tuple[str, ...],
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> dict[str, Quote]:
    """Load the newest valid quote per symbol or fail the complete group."""
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    cache_path = Path(path).expanduser()
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise QuoteCacheError(f"quote cache unavailable: {cache_path}") from exc
    if payload.get("source") != "SMART" or not isinstance(
        payload.get("symbols"), dict
    ):
        raise QuoteCacheError("quote cache has invalid metadata")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    result: dict[str, Quote] = {}
    for raw_symbol in symbols:
        symbol = raw_symbol.upper()
        rows = payload["symbols"].get(symbol)
        if not isinstance(rows, list) or not rows:
            raise QuoteCacheError(f"quote cache missing {symbol}")
        latest = rows[-1]
        if not isinstance(latest, dict):
            raise QuoteCacheError(f"quote cache has invalid {symbol} sample")
        try:
            observed_at = datetime.fromisoformat(str(latest["observed_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QuoteCacheError(
                f"quote cache has invalid {symbol} timestamp"
            ) from exc
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        age = (current - observed_at.astimezone(timezone.utc)).total_seconds()
        if age < -1 or age > max_age_seconds:
            raise QuoteCacheError(f"quote cache sample for {symbol} is stale")
        quote = Quote(
            symbol=symbol,
            bid=_optional_float(latest.get("bid")),
            ask=_optional_float(latest.get("ask")),
            last=_optional_float(latest.get("last")),
            close=_optional_float(latest.get("close")),
        )
        if quote.bid is None and quote.ask is None and quote.last is None:
            raise QuoteCacheError(f"quote cache sample for {symbol} has no live price")
        result[symbol] = quote
    return result


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QuoteCacheError("quote cache contains a non-numeric price") from exc
    if not math.isfinite(number) or number <= 0:
        return None
    return number
