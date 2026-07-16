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
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
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
    allowed_symbols: tuple[str, ...] = (
        "AAPL",
        "MSFT",
        "SPY",
        "SOXL",
        "SOXS",
        "TQQQ",
        "TECL",
    )
    vwap_symbols: tuple[str, ...] = ("SOXL", "TQQQ", "TECL")
    max_order_notional: float = 1_000.0
    market_data_type: str = "auto"
    request_timeout: float = 30.0
    live_bar_max_age_seconds: int = 420
    live_quote_cache_path: str | None = None
    live_quote_cache_max_age_seconds: float = 3.0
    live_quote_cache_refresh_seconds: float = 1.0
    live_quote_max_samples_per_symbol: int = 100
    max_daily_entries: int = 1
    state_dir: str = ".ibkr_bot_state/semiconductor_rotation_intraday"
    entry_order_price_offset_bps: float = 5.0
    entry_order_fill_wait_seconds: float = 20.0
    flatten_before_close_minutes: int = 10
    max_risk_per_trade: float = 10.0
    atr_window: int = 14
    atr_stop_multiple: float = 2.0
    historical_request_pause_seconds: float = 0.25
    arca_fallback_enabled: bool = False

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
        allowed_symbols=tuple(
            _list_env(
                "IBKR_ALLOWED_SYMBOLS",
                ["AAPL", "MSFT", "SPY", "SOXL", "SOXS", "TQQQ", "TECL"],
            )
        ),
        vwap_symbols=tuple(_list_env("IBKR_VWAP_SYMBOLS", ["SOXL", "TQQQ", "TECL"])),
        max_order_notional=float(os.getenv("IBKR_MAX_ORDER_NOTIONAL", "1000")),
        market_data_type=os.getenv("IBKR_MARKET_DATA_TYPE", "auto").strip().lower(),
        request_timeout=float(os.getenv("IBKR_REQUEST_TIMEOUT", "30")),
        live_bar_max_age_seconds=int(os.getenv("IBKR_LIVE_BAR_MAX_AGE_SECONDS", "420")),
        live_quote_cache_path=(
            os.getenv("IBKR_LIVE_QUOTE_CACHE_PATH", "").strip() or None
        ),
        live_quote_cache_max_age_seconds=float(
            os.getenv("IBKR_LIVE_QUOTE_CACHE_MAX_AGE_SECONDS", "3")
        ),
        live_quote_cache_refresh_seconds=float(
            os.getenv("IBKR_LIVE_QUOTE_CACHE_REFRESH_SECONDS", "1")
        ),
        live_quote_max_samples_per_symbol=int(
            os.getenv("IBKR_LIVE_QUOTE_MAX_SAMPLES_PER_SYMBOL", "100")
        ),
        max_daily_entries=int(os.getenv("IBKR_MAX_DAILY_ENTRIES", "1")),
        state_dir=os.getenv(
            "IBKR_STATE_DIR", ".ibkr_bot_state/semiconductor_rotation_intraday"
        ),
        entry_order_price_offset_bps=float(
            os.getenv("IBKR_ENTRY_ORDER_PRICE_OFFSET_BPS", "5")
        ),
        entry_order_fill_wait_seconds=float(
            os.getenv("IBKR_ENTRY_ORDER_FILL_WAIT_SECONDS", "20")
        ),
        flatten_before_close_minutes=int(
            os.getenv("IBKR_FLATTEN_BEFORE_CLOSE_MINUTES", "10")
        ),
        max_risk_per_trade=float(os.getenv("IBKR_MAX_RISK_PER_TRADE", "10")),
        atr_window=int(os.getenv("IBKR_ATR_WINDOW", "14")),
        atr_stop_multiple=float(os.getenv("IBKR_ATR_STOP_MULTIPLE", "2")),
        historical_request_pause_seconds=float(
            os.getenv("IBKR_HISTORICAL_REQUEST_PAUSE_SECONDS", "0.25")
        ),
        arca_fallback_enabled=_bool_env("IBKR_ARCA_FALLBACK_ENABLED", False),
    )
