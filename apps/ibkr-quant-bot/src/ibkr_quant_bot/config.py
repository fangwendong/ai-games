from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_local_env(path: str = ".env") -> None:
    env_path = Path.cwd() / path
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _list_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [part.strip().upper() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 4001
    client_id: int = 42
    readonly: bool = True
    account: str | None = None
    trading_mode: str = "paper"
    allow_live_trading: bool = False
    dry_run: bool = True
    allowed_symbols: tuple[str, ...] = ("AAPL", "MSFT", "SPY")
    vwap_symbols: tuple[str, ...] = ("SOXL", "TQQQ", "TECL")
    max_order_notional: float = 1_000.0
    market_data_type: str = "auto"
    request_timeout: float = 30.0
    live_bar_max_age_seconds: int = 420

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live"


def load_settings() -> Settings:
    _load_local_env()
    return Settings(
        host=os.getenv("IBKR_HOST", "127.0.0.1"),
        port=int(os.getenv("IBKR_PORT", "4001")),
        client_id=int(os.getenv("IBKR_CLIENT_ID", "42")),
        readonly=_bool_env("IBKR_READONLY", True),
        account=os.getenv("IBKR_ACCOUNT") or None,
        trading_mode=os.getenv("IBKR_TRADING_MODE", "paper").strip().lower(),
        allow_live_trading=_bool_env("IBKR_ALLOW_LIVE_TRADING", False),
        dry_run=_bool_env("IBKR_DRY_RUN", True),
        allowed_symbols=tuple(_list_env("IBKR_ALLOWED_SYMBOLS", ["AAPL", "MSFT", "SPY"])),
        vwap_symbols=tuple(_list_env("IBKR_VWAP_SYMBOLS", ["SOXL", "TQQQ", "TECL"])),
        max_order_notional=float(os.getenv("IBKR_MAX_ORDER_NOTIONAL", "1000")),
        market_data_type=os.getenv("IBKR_MARKET_DATA_TYPE", "auto").strip().lower(),
        request_timeout=float(os.getenv("IBKR_REQUEST_TIMEOUT", "30")),
        live_bar_max_age_seconds=int(os.getenv("IBKR_LIVE_BAR_MAX_AGE_SECONDS", "420")),
    )
