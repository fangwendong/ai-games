from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .models import Bar, MarketSession


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def expected_session_timestamps(
    session: MarketSession, *, bar_minutes: int = 5
) -> tuple[datetime, ...]:
    if bar_minutes < 1:
        raise ValueError("bar_minutes must be positive")
    step = timedelta(minutes=bar_minutes)
    current = session.opens_at
    expected: list[datetime] = []
    while current < session.closes_at:
        expected.append(_utc(current))
        current += step
    if current != session.closes_at:
        raise ValueError(
            f"session {session.session_date.isoformat()} is not divisible into "
            f"{bar_minutes}-minute bars"
        )
    return tuple(expected)


def validate_recent_cached_sessions(
    bars_by_symbol: dict[str, list[Bar]],
    sessions: dict[date, MarketSession],
    *,
    now: datetime,
    recent_sessions: int = 2,
    bar_minutes: int = 5,
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
        expected = expected_session_timestamps(session, bar_minutes=bar_minutes)
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
