from __future__ import annotations

import os
from dataclasses import dataclass


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
    port: int = 7497
    client_id: int = 42
    readonly: bool = True
    account: str | None = None
    trading_mode: str = "paper"
    allow_live_trading: bool = False
    dry_run: bool = True
    allowed_symbols: tuple[str, ...] = ("AAPL", "MSFT", "SPY")
    max_order_notional: float = 1_000.0
    market_data_type: str = "delayed"

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live"


def load_settings() -> Settings:
    return Settings(
        host=os.getenv("IBKR_HOST", "127.0.0.1"),
        port=int(os.getenv("IBKR_PORT", "7497")),
        client_id=int(os.getenv("IBKR_CLIENT_ID", "42")),
        readonly=_bool_env("IBKR_READONLY", True),
        account=os.getenv("IBKR_ACCOUNT") or None,
        trading_mode=os.getenv("IBKR_TRADING_MODE", "paper").strip().lower(),
        allow_live_trading=_bool_env("IBKR_ALLOW_LIVE_TRADING", False),
        dry_run=_bool_env("IBKR_DRY_RUN", True),
        allowed_symbols=tuple(_list_env("IBKR_ALLOWED_SYMBOLS", ["AAPL", "MSFT", "SPY"])),
        max_order_notional=float(os.getenv("IBKR_MAX_ORDER_NOTIONAL", "1000")),
        market_data_type=os.getenv("IBKR_MARKET_DATA_TYPE", "delayed").strip().lower(),
    )
