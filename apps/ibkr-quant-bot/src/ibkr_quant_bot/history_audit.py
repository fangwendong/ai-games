from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .historical_cache import load_bars
from .models import Bar


NEW_YORK = ZoneInfo("America/New_York")
EXPECTED_SESSION_BAR_COUNTS = {42, 78}


@dataclass(frozen=True)
class SymbolHistoryAudit:
    symbol: str
    first_session: date | None
    latest_session: date | None
    session_count: int
    bar_count: int
    boundary_partial_sessions: tuple[date, ...]
    incomplete_sessions: tuple[date, ...]
    non_five_minute_gap_sessions: tuple[date, ...]
    misaligned_session_time_sessions: tuple[date, ...]
    missing_sessions_within_history: tuple[date, ...]


@dataclass(frozen=True)
class HistoryAuditReport:
    status: str
    expected_latest_session: date | None
    recent_sessions: tuple[date, ...]
    symbols: tuple[SymbolHistoryAudit, ...]
    errors: tuple[str, ...]


def _session_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(NEW_YORK).date()


def _time_key(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def audit_historical_bars(
    bars_by_symbol: dict[str, list[Bar]], *, recent_session_count: int = 2
) -> HistoryAuditReport:
    if recent_session_count < 1:
        raise ValueError("recent_session_count must be positive")
    if not bars_by_symbol:
        raise ValueError("at least one symbol is required")

    grouped: dict[str, dict[date, list[Bar]]] = {}
    for raw_symbol, bars in bars_by_symbol.items():
        symbol = raw_symbol.upper()
        daily: dict[date, list[Bar]] = defaultdict(list)
        for bar in bars:
            daily[_session_date(bar.time)].append(bar)
        grouped[symbol] = daily

    calendar = sorted({day for daily in grouped.values() for day in daily})
    expected_latest = calendar[-1] if calendar else None
    recent = tuple(calendar[-recent_session_count:])
    errors: list[str] = []
    audits: list[SymbolHistoryAudit] = []

    for symbol in sorted(grouped):
        daily = grouped[symbol]
        days = sorted(daily)
        first = days[0] if days else None
        latest = days[-1] if days else None
        boundary_partial: list[date] = []
        incomplete: list[date] = []
        gap_sessions: list[date] = []
        misaligned_sessions: list[date] = []
        if not days:
            errors.append(f"{symbol}: no cached bars")
        for day in days:
            timeline = sorted(_time_key(bar.time) for bar in daily[day])
            if len(timeline) not in EXPECTED_SESSION_BAR_COUNTS:
                if day == first:
                    boundary_partial.append(day)
                else:
                    incomplete.append(day)
            gaps = [
                (later - earlier).total_seconds()
                for earlier, later in zip(timeline, timeline[1:])
            ]
            if any(gap != 300 for gap in gaps):
                gap_sessions.append(day)
            if len(timeline) in EXPECTED_SESSION_BAR_COUNTS:
                local_times = sorted(
                    (
                        bar.time
                        if bar.time.tzinfo is None
                        else bar.time.astimezone(NEW_YORK)
                    )
                    for bar in daily[day]
                )
                first_minutes = local_times[0].hour * 60 + local_times[0].minute
                last_minutes = local_times[-1].hour * 60 + local_times[-1].minute
                expected_last = 15 * 60 + 55 if len(timeline) == 78 else 12 * 60 + 55
                if first_minutes != 9 * 60 + 30 or last_minutes != expected_last:
                    misaligned_sessions.append(day)

        missing: list[date] = []
        if first is not None and latest is not None:
            missing = [day for day in calendar if first <= day <= latest and day not in daily]
        if latest != expected_latest:
            errors.append(
                f"{symbol}: latest session {latest} does not match {expected_latest}"
            )
        missing_recent = [day for day in recent if day not in daily]
        if missing_recent:
            errors.append(
                f"{symbol}: missing recent sessions "
                + ",".join(day.isoformat() for day in missing_recent)
            )
        if incomplete:
            errors.append(f"{symbol}: {len(incomplete)} incomplete internal sessions")
        if gap_sessions:
            errors.append(f"{symbol}: {len(gap_sessions)} sessions contain non-5-minute gaps")
        if misaligned_sessions:
            errors.append(
                f"{symbol}: {len(misaligned_sessions)} sessions have misaligned RTH times"
            )
        if missing:
            errors.append(f"{symbol}: {len(missing)} missing sessions within cached history")

        audits.append(
            SymbolHistoryAudit(
                symbol=symbol,
                first_session=first,
                latest_session=latest,
                session_count=len(days),
                bar_count=sum(len(rows) for rows in daily.values()),
                boundary_partial_sessions=tuple(boundary_partial),
                incomplete_sessions=tuple(incomplete),
                non_five_minute_gap_sessions=tuple(gap_sessions),
                misaligned_session_time_sessions=tuple(misaligned_sessions),
                missing_sessions_within_history=tuple(missing),
            )
        )

    return HistoryAuditReport(
        status="passed" if not errors else "failed",
        expected_latest_session=expected_latest,
        recent_sessions=recent,
        symbols=tuple(audits),
        errors=tuple(errors),
    )


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibkr-history-audit")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--bar-size", default="5 mins")
    parser.add_argument("--recent-sessions", type=int, default=2)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args(argv)

    symbols = tuple(dict.fromkeys(item.upper() for item in args.symbols))
    report = audit_historical_bars(
        {
            symbol: load_bars(args.data_dir, symbol, args.bar_size)
            for symbol in symbols
        },
        recent_session_count=args.recent_sessions,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True, default=_json_default))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
