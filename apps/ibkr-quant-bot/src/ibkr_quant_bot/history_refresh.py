from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .models import Bar, MarketSession


def _bar_size_seconds(bar_size: str) -> int:
    parts = bar_size.strip().lower().split()
    if len(parts) < 2:
        raise ValueError(f"unsupported bar size: {bar_size}")
    try:
        value = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"unsupported bar size: {bar_size}") from exc
    unit = parts[1]
    if unit.startswith("sec"):
        return value
    if unit.startswith("min"):
        return value * 60
    if unit.startswith("hour"):
        return value * 60 * 60
    if unit.startswith("day"):
        return value * 24 * 60 * 60
    raise ValueError(f"unsupported bar size: {bar_size}")


def schedule_lookback_days(recent_sessions: int) -> int:
    """Bound the IBKR schedule request to the recent validation window."""
    if recent_sessions < 1:
        raise ValueError("recent_sessions must be positive")
    return max(10, recent_sessions * 4)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def expected_session_timestamps(
    session: MarketSession, *, bar_size: str = "5 mins"
) -> tuple[datetime, ...]:
    step_seconds = _bar_size_seconds(bar_size)
    if step_seconds < 1:
        raise ValueError("bar_size must be positive")
    step = timedelta(seconds=step_seconds)
    current = session.opens_at
    expected: list[datetime] = []
    while current < session.closes_at:
        expected.append(_utc(current))
        current += step
    if current != session.closes_at:
        raise ValueError(
            f"session {session.session_date.isoformat()} is not divisible into "
            f"{bar_size} bars"
        )
    return tuple(expected)


def validate_recent_cached_sessions(
    bars_by_symbol: dict[str, list[Bar]],
    sessions: dict[date, MarketSession],
    *,
    now: datetime,
    recent_sessions: int = 2,
    bar_size: str = "5 mins",
) -> dict[str, object]:
    """Validate cached bars against IBKR's completed historical RTH schedule."""
    if recent_sessions < 1:
        raise ValueError("recent_sessions must be positive")
    if not bars_by_symbol:
        raise ValueError("historical refresh requires at least one symbol")

    now_utc = _utc(now)
    completed = sorted(
        session_date
        for session_date, session in sessions.items()
        if _utc(session.closes_at) <= now_utc
    )
    if len(completed) < recent_sessions:
        raise ValueError(
            f"IBKR historical schedule has only {len(completed)} completed sessions; "
            f"need {recent_sessions}"
        )
    checked = completed[-recent_sessions:]
    report_counts: dict[str, dict[str, int]] = {}
    for session_date in checked:
        session = sessions[session_date]
        expected = expected_session_timestamps(session, bar_size=bar_size)
        report_counts[session_date.isoformat()] = {}
        for raw_symbol, bars in bars_by_symbol.items():
            symbol = raw_symbol.upper()
            actual = tuple(
                sorted(
                    _utc(bar.time)
                    for bar in bars
                    if session.opens_at
                    <= bar.time.astimezone(session.opens_at.tzinfo)
                    < session.closes_at
                )
            )
            if len(actual) != len(set(actual)):
                raise ValueError(
                    f"historical refresh found duplicate {symbol} bars on "
                    f"{session_date.isoformat()}"
                )
            if actual != expected:
                missing = len(set(expected) - set(actual))
                extra = len(set(actual) - set(expected))
                raise ValueError(
                    f"historical refresh timeline mismatch for {symbol} on "
                    f"{session_date.isoformat()}: expected={len(expected)} "
                    f"actual={len(actual)} missing={missing} extra={extra}"
                )
            report_counts[session_date.isoformat()][symbol] = len(actual)

    return {
        "latest_completed_session": checked[-1].isoformat(),
        "checked_sessions": [item.isoformat() for item in checked],
        "counts": report_counts,
    }
