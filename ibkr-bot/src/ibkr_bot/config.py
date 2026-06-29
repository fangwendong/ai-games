from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared, this keeps imports friendly.
    load_dotenv = None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in {None, ""} else float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in {None, ""} else int(raw)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    client_id: int
    account: str | None
    trading_mode: str
    dry_run: bool
    allow_live: bool
    symbols: tuple[str, ...]
    max_notional_per_order: float
    max_position_notional: float
    max_orders_per_day: int
    max_daily_loss: float
    allow_market_orders: bool
    database_path: Path
    alert_command: str | None

    @property
    def live_trading_enabled(self) -> bool:
        return self.trading_mode == "live" and self.allow_live and not self.dry_run


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    if load_dotenv and env_file:
        load_dotenv(env_file, override=False)

    symbols = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("IBKR_SYMBOLS", "SPY,QQQ").split(",")
        if symbol.strip()
    )
    trading_mode = os.getenv("IBKR_TRADING_MODE", "paper").strip().lower()
    if trading_mode not in {"paper", "live"}:
        raise ValueError("IBKR_TRADING_MODE must be either 'paper' or 'live'")

    return Settings(
        host=os.getenv("IBKR_HOST", "127.0.0.1"),
        port=_int_env("IBKR_PORT", 4002),
        client_id=_int_env("IBKR_CLIENT_ID", 17),
        account=os.getenv("IBKR_ACCOUNT") or None,
        trading_mode=trading_mode,
        dry_run=_bool_env("IBKR_DRY_RUN", True),
        allow_live=_bool_env("IBKR_ALLOW_LIVE", False),
        symbols=symbols,
        max_notional_per_order=_float_env("MAX_NOTIONAL_PER_ORDER", 1000.0),
        max_position_notional=_float_env("MAX_POSITION_NOTIONAL", 5000.0),
        max_orders_per_day=_int_env("MAX_ORDERS_PER_DAY", 10),
        max_daily_loss=_float_env("MAX_DAILY_LOSS", 250.0),
        allow_market_orders=_bool_env("ALLOW_MARKET_ORDERS", False),
        database_path=Path(os.getenv("DATABASE_PATH", "bot.sqlite3")),
        alert_command=os.getenv("ALERT_COMMAND") or None,
    )

