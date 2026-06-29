from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ibkr_bot.models import OrderIntent, RiskDecision


SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_intents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  order_type TEXT NOT NULL,
  limit_price REAL,
  reason TEXT NOT NULL,
  dry_run INTEGER NOT NULL,
  risk_accepted INTEGER NOT NULL,
  risk_reasons_json TEXT NOT NULL,
  broker_order_id TEXT
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  broker_order_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity REAL NOT NULL,
  price REAL NOT NULL,
  payload_json TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def orders_today(self) -> int:
        start = date.today().isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM order_intents WHERE substr(created_at, 1, 10) = ?",
                (start,),
            ).fetchone()
        return int(row["count"])

    def record_signal(self, symbol: str, strategy: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO signals (created_at, symbol, strategy, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (datetime.now(UTC).isoformat(), symbol, strategy, json.dumps(payload, sort_keys=True)),
            )

    def record_order_intent(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        dry_run: bool,
        broker_order_id: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_intents (
                  created_at, symbol, side, quantity, order_type, limit_price, reason,
                  dry_run, risk_accepted, risk_reasons_json, broker_order_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.created_at.isoformat(),
                    intent.contract.symbol,
                    intent.side.value,
                    intent.quantity,
                    intent.order_type.value,
                    intent.limit_price,
                    intent.reason,
                    int(dry_run),
                    int(decision.accepted),
                    json.dumps(decision.reasons),
                    broker_order_id,
                ),
            )

