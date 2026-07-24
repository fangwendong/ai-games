from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .live_review_log import current_session_date


NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_TRADE_RECORD_PATH = Path("/home/fwd/data/ibkr-quant-bot/historical/trade.json")


@dataclass(frozen=True)
class TradeRecordUpdate:
    session_date: str
    appended: bool
    output_path: Path
    message: str


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_existing_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "generated_at": None,
            "source": "ibkr_quant_bot live journals",
            "location": str(path),
            "days": [],
        }
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"trade record ledger must be a JSON object: {path}")
    days = payload.get("days", [])
    if not isinstance(days, list):
        raise ValueError(f"trade record ledger has invalid days list: {path}")
    payload["days"] = days
    payload.setdefault("source", "ibkr_quant_bot live journals")
    payload.setdefault("location", str(path))
    return payload


def _parse_iso_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "不可用"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)
    return moment.astimezone(NEW_YORK).isoformat()


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(round(number))


def _infer_exit_note(order_ref: object, order_type: object) -> str:
    ref = str(order_ref or "").lower()
    order_kind = str(order_type or "").upper()
    if "protect-stop" in ref or "stop" in ref:
        return "protective stop"
    if "protect-take" in ref or "take" in ref:
        return "protective take"
    if "eod-exit" in ref or "flatten" in ref:
        return "end-of-day flatten"
    if order_kind == "MKT":
        return "software exit"
    return "exit"


def _entry_trade(entry: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(entry.get("symbol") or "").upper()
    quantity = _to_int(entry.get("filled_quantity") or entry.get("quantity"))
    price = _to_float(entry.get("average_fill_price"))
    timestamp = _parse_iso_time(entry.get("time"))
    if not symbol or quantity is None or price is None:
        return None
    return {
        "time": timestamp,
        "symbol": symbol,
        "side": "buy",
        "quantity": quantity,
        "average_fill_price": price,
        "kind": "entry",
        "note": "entry signal satisfied",
    }


def _exit_trade(record: dict[str, Any]) -> dict[str, Any] | None:
    request = record.get("request", {})
    status = record.get("status", {})
    if not isinstance(request, dict) or not isinstance(status, dict):
        return None
    if str(request.get("action") or "").upper() != "SELL":
        return None
    if not request.get("reduce_only"):
        return None
    lifecycle = str(status.get("lifecycle") or status.get("status") or "").lower()
    if lifecycle != "filled":
        return None
    symbol = str(request.get("symbol") or "").upper()
    quantity = _to_int(status.get("filled") or request.get("quantity"))
    price = _to_float(status.get("avg_fill_price") or status.get("last_fill_price"))
    timestamp = _parse_iso_time(record.get("recorded_at"))
    if not symbol or quantity is None or price is None:
        return None
    return {
        "time": timestamp,
        "symbol": symbol,
        "side": "sell",
        "quantity": quantity,
        "average_fill_price": price,
        "kind": "exit",
        "note": _infer_exit_note(request.get("order_ref"), request.get("order_type")),
    }


def _build_day_record(state_dir: Path, session_date: str) -> dict[str, Any] | None:
    trades: list[dict[str, Any]] = []
    entries_path = state_dir / f"entries-{session_date}.json"
    if entries_path.exists():
        payload = _load_json(entries_path)
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    trade = _entry_trade(entry)
                    if trade is not None:
                        trades.append(trade)

    orders_path = state_dir / f"orders-{session_date}.jsonl"
    if orders_path.exists():
        for raw_line in orders_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            trade = _exit_trade(record)
            if trade is not None:
                trades.append(trade)

    if not trades:
        return None

    trades.sort(key=lambda item: item.get("time") or "")
    return {
        "date": session_date,
        "trades": trades,
    }


def append_trade_record(
    *,
    state_dir: Path,
    output_path: Path = DEFAULT_TRADE_RECORD_PATH,
    session_date: str | None = None,
) -> TradeRecordUpdate:
    session_date = session_date or current_session_date()
    ledger = _load_existing_ledger(output_path)
    days = ledger["days"]
    if any(isinstance(day, dict) and day.get("date") == session_date for day in days):
        return TradeRecordUpdate(
            session_date=session_date,
            appended=False,
            output_path=output_path,
            message=f"trade record already contains {session_date}",
        )

    day_record = _build_day_record(state_dir=state_dir, session_date=session_date)
    if day_record is None:
        return TradeRecordUpdate(
            session_date=session_date,
            appended=False,
            output_path=output_path,
            message=f"no filled trades found for {session_date}",
        )

    days.append(day_record)
    days.sort(key=lambda item: str(item.get("date") or ""))
    ledger["days"] = days
    ledger["generated_at"] = datetime.now(NEW_YORK).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return TradeRecordUpdate(
        session_date=session_date,
        appended=True,
        output_path=output_path,
        message=f"appended trade record for {session_date}",
    )
