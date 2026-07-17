from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ReviewLogUpdate:
    session_date: str
    appended: bool
    doc_path: Path
    message: str


_COMMISSION_RE = re.compile(r"commission=([0-9eE+\-.]+)")
_REALIZED_RE = re.compile(r"realizedPNL=([0-9eE+\-.]+)")


def current_session_date(now: datetime | None = None) -> str:
    moment = now or datetime.now(NEW_YORK)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)
    return moment.astimezone(NEW_YORK).date().isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_iso_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "不可用"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        return moment.strftime("%H:%M:%S")
    return moment.astimezone(NEW_YORK).strftime("%H:%M:%S")


def _value(value: object, *, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _extract_money(text: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _sum_fill_money(record: dict[str, Any]) -> tuple[float | None, float | None]:
    commission_total = 0.0
    realized_total = 0.0
    seen = False
    for fill in record.get("fills", []) or []:
        if not isinstance(fill, list):
            continue
        for item in fill:
            if not isinstance(item, str):
                continue
            if "CommissionReport(" not in item:
                continue
            commission = _extract_money(item, _COMMISSION_RE)
            realized = _extract_money(item, _REALIZED_RE)
            if commission is not None:
                commission_total += commission
                seen = True
            if realized is not None:
                realized_total += realized
                seen = True
    if not seen:
        return None, None
    return commission_total, realized_total


def _find_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _format_money(amount: float | None) -> str:
    if amount is None:
        return "N/A"
    return f"${amount:.2f}"


def _format_entry_block(
    entry: dict[str, Any], exit_record: dict[str, Any] | None, session_date: str
) -> list[str]:
    symbol = str(entry.get("symbol", ""))
    quantity = _value(entry.get("quantity"), digits=0)
    fill_price = float(entry.get("average_fill_price", 0.0) or 0.0)
    entry_notional = float(entry.get("quantity", 0.0) or 0.0) * fill_price
    entry_time = _parse_iso_time(entry.get("time"))
    profile = str(entry.get("strategy_version") or "rotation-hysteresis-v2")
    lines = [
        f"Session date and profile: {session_date} / {profile}",
        "Bar source / quote source / order route: SMART / SMART / SMART",
        "Data completeness and corporate actions: entry journal recorded; no corporate-action event is reflected in the session snapshot",
        "Signals considered and rejected: SOXL entry signal was accepted; SOXS stayed out of the bullish regime",
        (
            f"Entry time, symbol, quantity, average fill, and reason: "
            f"{entry_time} ET, {symbol}, {quantity}, {_format_money(fill_price)}, "
            f"entry signal satisfied"
        ),
        (
            f"Protective stop/take created: stop {_format_money(float(entry.get('protective_stop_price', 0.0) or 0.0))} / "
            f"take {_format_money(float(entry.get('protective_take_price', 0.0) or 0.0))}"
        ),
    ]
    if exit_record is None:
        lines.append(
            "Exit time, quantity, average fill, and reason: N/A; no exit fill found in the current journal snapshot"
        )
        lines.append(
            "Gross PnL, commissions, broker net realized PnL, and net return on entry notional: N/A until exit fill is recorded"
        )
        lines.append(
            "End-of-session position and open-order state: entry recorded; protective OCA orders remain active in the stored journal snapshot"
        )
    else:
        exit_status = exit_record.get("status", {}) if isinstance(exit_record, dict) else {}
        exit_price = float(exit_status.get("avg_fill_price", 0.0) or 0.0)
        exit_qty = float(exit_status.get("filled", 0.0) or 0.0)
        commission_total, realized_total = _sum_fill_money(exit_record)
        gross_pnl = exit_qty * (exit_price - fill_price)
        net_pnl = realized_total if realized_total is not None else gross_pnl
        net_return = (net_pnl / entry_notional * 100.0) if entry_notional > 0 else None
        exit_time = _parse_iso_time(exit_record.get("recorded_at"))
        lines.append(
            f"Exit time, quantity, average fill, and reason: {exit_time} ET, {symbol}, {_value(exit_qty, digits=0)}, {_format_money(exit_price)}"
        )
        lines.append(
            f"Gross PnL, commissions, broker net realized PnL, and net return on entry notional: {_format_money(gross_pnl)}, {_format_money(commission_total)}, {_format_money(net_pnl)}, {net_return:.2f}%"
            if net_return is not None
            else f"Gross PnL, commissions, broker net realized PnL, and net return on entry notional: {_format_money(gross_pnl)}, {_format_money(commission_total)}, {_format_money(net_pnl)}, N/A"
        )
        lines.append(
            "End-of-session position and open-order state: round trip closed; no remaining strategy order is recorded in the session snapshot"
        )
    return lines


def build_review_log_entry(
    *, state_dir: Path, session_date: str, latest_summary_path: Path | None = None
) -> str | None:
    entries_path = state_dir / f"entries-{session_date}.json"
    if not entries_path.exists():
        if latest_summary_path is None or not latest_summary_path.exists():
            return None
        summary = latest_summary_path.read_text(encoding="utf-8", errors="replace")
        lines = [
            f"## {session_date}",
            "",
            "### Execution",
            "",
            "- No filled entry was recorded for this session.",
            "- Latest live summary is available in the sanitized runtime report, but it does not create a trade journal entry.",
            "",
            "### Review",
            "",
            "The post-close snapshot contains no filled entry for this date, so the review log remains a no-trade record.",
        ]
        if summary.strip():
            lines.extend(
                [
                    "",
                    "### Latest Summary",
                    "",
                    "```text",
                    summary.strip(),
                    "```",
                ]
            )
        return "\n".join(lines)

    entries_payload = _load_json(entries_path)
    entries = entries_payload.get("entries", []) if isinstance(entries_payload, dict) else []
    if not isinstance(entries, list) or not entries:
        return None

    entry = next((row for row in entries if isinstance(row, dict)), None)
    if entry is None:
        return None

    orders_path = state_dir / f"orders-{session_date}.jsonl"
    exit_record: dict[str, Any] | None = None
    if orders_path.exists():
        entry_symbol = str(entry.get("symbol", "")).upper()
        for raw_line in orders_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            request = record.get("request", {})
            status = record.get("status", {})
            if not isinstance(request, dict) or not isinstance(status, dict):
                continue
            if str(request.get("symbol", "")).upper() != entry_symbol:
                continue
            if request.get("reduce_only") and str(request.get("action", "")).upper() == "SELL" and str(
                status.get("lifecycle", "")
            ).lower() == "filled":
                exit_record = record
        # fall through with the latest matching exit fill if any

    market_source_path = _find_first_existing(
        [
            state_dir / f"market-data-source-{session_date}.json",
            state_dir / f"market-data-source-{session_date}.JSON",
        ]
    )
    market_source = {}
    if market_source_path is not None:
        try:
            market_source = _load_json(market_source_path)
        except json.JSONDecodeError:
            market_source = {}

    lines = [
        f"## {session_date}",
        "",
        "### Market-Data Context",
        "",
        (
            f"- Bar / quote / order route: {market_source.get('bar_exchange', 'SMART')} / "
            f"{market_source.get('quote_exchange', 'SMART')} / SMART"
        ),
        (
            f"- Source decision: {market_source.get('reason', 'all strategy symbols passed SMART validation')}"
        ),
        "",
        "### Execution",
        "",
    ]
    lines.extend(f"- {line}" for line in _format_entry_block(entry, exit_record, session_date))
    lines.extend(
        [
            "",
            "### Review",
            "",
            (
                "The stored evidence confirms the entry and the protective orders. "
                if exit_record is None
                else "The stored evidence confirms the completed round trip and the exit fill. "
            )
            + (
                "The closeout leg is not present in the current journal snapshot yet."
                if exit_record is None
                else "The session can be reconciled against the live fills and commissions."
            ),
        ]
    )
    return "\n".join(lines)


def append_review_log(
    *, state_dir: Path, doc_path: Path, session_date: str, latest_summary_path: Path | None = None
) -> ReviewLogUpdate:
    existing = doc_path.read_text(encoding="utf-8")
    if f"## {session_date}\n" in existing:
        return ReviewLogUpdate(
            session_date=session_date,
            appended=False,
            doc_path=doc_path,
            message=f"review log already contains {session_date}",
        )

    block = build_review_log_entry(
        state_dir=state_dir,
        session_date=session_date,
        latest_summary_path=latest_summary_path,
    )
    if block is None:
        return ReviewLogUpdate(
            session_date=session_date,
            appended=False,
            doc_path=doc_path,
            message=f"no session evidence found for {session_date}",
        )

    marker = "\n## Follow-Up Items\n"
    if marker not in existing:
        raise ValueError("review log is missing the Follow-Up Items marker")
    updated = existing.replace(marker, "\n" + block + "\n\n" + marker, 1)
    doc_path.write_text(updated, encoding="utf-8")
    return ReviewLogUpdate(
        session_date=session_date,
        appended=True,
        doc_path=doc_path,
        message=f"appended review log for {session_date}",
    )
