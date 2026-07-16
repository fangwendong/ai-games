from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from dataclasses import asdict, replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from time import sleep as blocking_sleep
from zoneinfo import ZoneInfo

from .broker import BrokerError, IbkrBroker, format_table
from .backtest import (
    BacktestCostModel,
    evaluate_fixed_strategy_walk_forward,
    evaluate_parameter_stability,
    validate_historical_bar_coverage,
)
from .config import Settings, load_settings
from .historical_cache import (
    load_bars,
    require_market_data_source,
    save_bars_by_day,
)
from .history_refresh import schedule_lookback_days, validate_recent_cached_sessions
from .models import Bar, MarketSession, Quote, StrategyDecision, TradeRequest
from .market_context_cache import (
    MarketContextCacheError,
    load_cached_market_session,
    load_fresh_cached_bars,
    write_market_context_cache,
)
from .quote_cache import QuoteCacheError, QuoteCacheWriter, load_fresh_quotes
from .risk import RiskManager
from .strategy import (
    IntradayMomentumStrategy,
    MovingAverageStrategy,
    SemiconductorRotationStrategy,
    VwapPullbackStrategy,
)

NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_MOMENTUM_PROFILE = "rotation-hysteresis-v2"
FROZEN_ROTATION_HYSTERESIS_VERSION = "rotation-hysteresis-v1"
FROZEN_ROTATION_HYSTERESIS_PARAMETERS: dict[str, object] = {
    "symbols": ("SOXL", "SOXS"),
    "benchmark_symbol": "QQQ",
    "fast_window": 13,
    "slow_window": 21,
    "trend_window": 34,
    "trend_lookback": 5,
    "benchmark_fast_window": 13,
    "benchmark_slow_window": 21,
    "benchmark_trend_lookback": 5,
    "min_bars": 30,
    "long_stop_loss_pct": 0.006,
    "long_take_profit_pct": 0.0375,
    "long_min_confirm_bars": 1,
    "long_min_trend_gap": 0.001,
    "long_min_vwap_gap": 0.00025,
    "long_min_score": 0.006,
    "short_stop_loss_pct": 0.006,
    "short_take_profit_pct": 0.0375,
    "short_min_confirm_bars": 2,
    "short_min_trend_gap": 0.0015,
    "short_min_vwap_gap": 0.00025,
    "short_min_score": 0.006,
    "require_vwap_confirmation": True,
    "require_benchmark_confirmation": True,
    "atr_window": 14,
    "atr_stop_multiple": 2.0,
    "use_exit_hysteresis": True,
    "exit_confirm_bars": 3,
    "benchmark_exit_confirm_bars": 3,
    "exit_reversal_votes": 2,
}
ROTATION_HYSTERESIS_V2_VERSION = "rotation-hysteresis-v2"
ROTATION_HYSTERESIS_V2_PARAMETERS: dict[str, object] = {
    **FROZEN_ROTATION_HYSTERESIS_PARAMETERS,
    "profit_lock_activation_pct": 0.03,
    "profit_lock_drawdown_pct": 0.006,
    "entry_fill_cutoff_et_minutes": 13 * 60 + 30,
}
MOMENTUM_PROFILE_CHOICES = [
    "balanced",
    "high-frequency",
    "rotation",
    "rotation-hysteresis",
    "rotation-hysteresis-v1",
    "rotation-hysteresis-v2",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ibkr-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "doctor", help="show local configuration and dependency status"
    )
    subparsers.add_parser(
        "heartbeat", help="verify the Gateway API with a server-time round trip"
    )

    refresh = subparsers.add_parser(
        "refresh-history",
        help="refresh recent history and validate IBKR's historical RTH schedule",
    )
    refresh.add_argument(
        "--symbols", nargs="+", default=["SOXL", "SOXS", "QQQ"]
    )
    refresh.add_argument("--duration", default="10 D")
    refresh.add_argument("--bar-size", default="5 mins")
    refresh.add_argument("--recent-sessions", type=int, default=2)
    refresh.add_argument("--data-dir", default=".ibkr_bot_data/historical")
    refresh.add_argument(
        "--market-data-exchange",
        choices=["SMART", "ARCA"],
        default="SMART",
        help="single exchange used for every symbol in this cache",
    )

    quote = subparsers.add_parser("quote", help="fetch a market data snapshot")
    quote.add_argument("symbol")

    stream_quotes = subparsers.add_parser(
        "stream-live-quotes",
        help="maintain an atomic bounded SMART quote cache",
    )
    stream_quotes.add_argument(
        "--symbols", nargs="+", default=["QQQ", "SOXL", "SOXS"]
    )
    stream_quotes.add_argument("--cache-path", default=None)

    cache_context = subparsers.add_parser(
        "cache-live-context",
        help="precompute the SMART session calendar and completed 5-minute bars",
    )
    cache_context.add_argument(
        "--symbols", nargs="+", default=["QQQ", "SOXL", "SOXS"]
    )
    cache_context.add_argument("--cache-path", default=None)

    subparsers.add_parser("account", help="show account summary")
    subparsers.add_parser(
        "balance", help="show cash, net liquidation, buying power, margin, and PnL"
    )
    subparsers.add_parser("positions", help="show open positions")

    order = subparsers.add_parser(
        "order", help="validate and optionally submit an order"
    )
    order.add_argument("symbol")
    order.add_argument("action", choices=["BUY", "SELL"])
    order.add_argument("quantity", type=int)
    order.add_argument("--type", choices=["MKT", "LMT"], default="MKT")
    order.add_argument("--limit-price", type=float)
    order.add_argument(
        "--reference-price", type=float, help="price used for dry-run notional checks"
    )

    run_once = subparsers.add_parser(
        "run-once", help="run the sample moving-average strategy once"
    )
    run_once.add_argument("symbol")
    run_once.add_argument("--fast", type=int, default=5)
    run_once.add_argument("--slow", type=int, default=20)
    run_once.add_argument("--quantity", type=int, default=1)

    vwap = subparsers.add_parser(
        "vwap-pullback",
        help="scan SOXL/TQQQ/TECL and optionally auto-place limit orders",
    )
    vwap.add_argument(
        "--max-notional", type=float, default=None, help="cap per order notional"
    )

    momentum = subparsers.add_parser(
        "intraday-momentum",
        help="scan SOXL/TQQQ/TECL with an intraday momentum rotation rule and manage exits",
    )
    momentum.add_argument(
        "--max-notional", type=float, default=None, help="cap per order notional"
    )
    momentum.add_argument(
        "--profile",
        choices=MOMENTUM_PROFILE_CHOICES,
        default=DEFAULT_MOMENTUM_PROFILE,
        help="strategy preset; rotation-hysteresis-v2 is the current live profile",
    )
    momentum.add_argument(
        "--benchmark-symbol",
        type=str,
        default="QQQ",
        help="market regime benchmark symbol",
    )
    momentum.add_argument("--fast", type=int, default=13, help="fast EMA window")
    momentum.add_argument("--slow", type=int, default=21, help="slow EMA window")
    momentum.add_argument(
        "--trend-window", type=int, default=34, help="medium-term EMA regime window"
    )
    momentum.add_argument(
        "--trend-lookback", type=int, default=5, help="bars used for trend slope check"
    )
    momentum.add_argument(
        "--min-bars", type=int, default=30, help="minimum bars required before trading"
    )
    momentum.add_argument(
        "--stop-loss-pct", type=float, default=0.008, help="stop loss percentage"
    )
    momentum.add_argument(
        "--take-profit-pct", type=float, default=0.02, help="take profit percentage"
    )
    momentum.add_argument(
        "--min-confirm-bars",
        type=int,
        default=2,
        help="minimum consecutive bars above VWAP",
    )
    momentum.add_argument(
        "--min-trend-gap", type=float, default=0.0015, help="minimum fast/slow EMA gap"
    )
    momentum.add_argument(
        "--min-vwap-gap", type=float, default=0.0005, help="minimum close/vwap gap"
    )
    momentum.add_argument(
        "--min-score", type=float, default=0.008, help="minimum momentum score required"
    )
    momentum.add_argument(
        "--no-benchmark-confirmation",
        action="store_true",
        help="allow entries without the benchmark trend filter",
    )
    momentum.add_argument(
        "--no-vwap-confirmation",
        action="store_true",
        help="allow entries without the close being above VWAP",
    )

    backtest = subparsers.add_parser(
        "backtest-momentum",
        help="backtest the intraday momentum rotation rule with transaction costs",
    )
    backtest.add_argument(
        "--duration",
        default="3 Y",
        help="single historical request used for chronological walk-forward evaluation",
    )
    backtest.add_argument(
        "--train-days", type=int, default=252, help="walk-forward training window"
    )
    backtest.add_argument(
        "--test-days", type=int, default=63, help="walk-forward out-of-sample window"
    )
    backtest.add_argument(
        "--step-days", type=int, default=63, help="days between walk-forward folds"
    )
    backtest.add_argument(
        "--holdout-days", type=int, default=63, help="final untouched test window"
    )
    backtest.add_argument(
        "--max-notional", type=float, default=None, help="cap per order notional"
    )
    backtest.add_argument(
        "--capital", type=float, default=1_000.0, help="starting capital"
    )
    backtest.add_argument(
        "--profile",
        choices=MOMENTUM_PROFILE_CHOICES,
        default=DEFAULT_MOMENTUM_PROFILE,
        help="strategy preset; rotation-hysteresis-v2 is the current live profile",
    )
    backtest.add_argument(
        "--benchmark-symbol",
        type=str,
        default="QQQ",
        help="market regime benchmark symbol",
    )
    backtest.add_argument("--fast", type=int, default=13, help="fast EMA window")
    backtest.add_argument("--slow", type=int, default=21, help="slow EMA window")
    backtest.add_argument(
        "--trend-window", type=int, default=34, help="medium-term EMA regime window"
    )
    backtest.add_argument(
        "--trend-lookback", type=int, default=5, help="bars used for trend slope check"
    )
    backtest.add_argument(
        "--min-bars", type=int, default=30, help="minimum bars required before trading"
    )
    backtest.add_argument(
        "--stop-loss-pct", type=float, default=0.008, help="stop loss percentage"
    )
    backtest.add_argument(
        "--take-profit-pct", type=float, default=0.02, help="take profit percentage"
    )
    backtest.add_argument(
        "--min-confirm-bars",
        type=int,
        default=2,
        help="minimum consecutive bars above VWAP",
    )
    backtest.add_argument(
        "--min-trend-gap", type=float, default=0.0015, help="minimum fast/slow EMA gap"
    )
    backtest.add_argument(
        "--min-vwap-gap", type=float, default=0.0005, help="minimum close/vwap gap"
    )
    backtest.add_argument(
        "--min-score", type=float, default=0.008, help="minimum momentum score required"
    )
    backtest.add_argument(
        "--no-benchmark-confirmation",
        action="store_true",
        help="allow entries without the benchmark trend filter",
    )
    backtest.add_argument(
        "--no-vwap-confirmation",
        action="store_true",
        help="allow entries without the close being above VWAP",
    )
    backtest.add_argument(
        "--commission-per-order",
        type=float,
        default=1.0,
        help="commission per order (default: $1, calibrated from recent live fills)",
    )
    backtest.add_argument(
        "--slippage-bps",
        type=float,
        default=1.0,
        help="slippage in basis points per side",
    )
    backtest.add_argument(
        "--spread-bps", type=float, default=1.0, help="spread in basis points per side"
    )
    backtest.add_argument(
        "--data-dir",
        default=".ibkr_bot_data/historical",
        help="daily historical bar cache directory",
    )
    backtest.add_argument(
        "--reuse-data",
        action="store_true",
        help="run from cached daily bars without connecting to IBKR",
    )
    backtest.add_argument(
        "--market-data-exchange",
        choices=["SMART", "ARCA"],
        default="SMART",
        help="required source for all historical bars in this backtest",
    )

    return parser


def _print_settings(settings: Settings) -> None:
    safe = asdict(settings)
    print(json.dumps(safe, indent=2, sort_keys=True))


def _doctor(settings: Settings) -> int:
    _print_settings(settings)
    try:
        import ib_insync  # type: ignore  # noqa: F401
    except ImportError:
        print("ib_insync: missing")
        return 1
    print("ib_insync: installed")
    return 0


def _with_broker(settings: Settings) -> IbkrBroker:
    broker = IbkrBroker(settings)
    broker.connect()
    return broker


def _submit_or_print(
    broker: IbkrBroker, settings: Settings, request: TradeRequest, reason: str
):
    print(reason)
    if settings.readonly or settings.dry_run:
        print("dry-run: order not submitted")
        return
    trade = broker.place_order(request)
    print(trade)
    _record_order_state(settings, request, trade)
    return trade


def _trade_filled_quantity(trade) -> float:
    order_status = getattr(trade, "orderStatus", None)
    if order_status is None:
        return 0.0
    try:
        return float(getattr(order_status, "filled", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _trade_remaining_quantity(trade) -> float:
    order_status = getattr(trade, "orderStatus", None)
    if order_status is None:
        return 0.0
    try:
        return float(getattr(order_status, "remaining", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _trade_average_fill_price(trade) -> float:
    order_status = getattr(trade, "orderStatus", None)
    if order_status is None:
        return 0.0
    try:
        return float(getattr(order_status, "avgFillPrice", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _trade_lifecycle(trade) -> str:
    status = str(getattr(getattr(trade, "orderStatus", None), "status", "") or "")
    filled = _trade_filled_quantity(trade)
    remaining = _trade_remaining_quantity(trade)
    if status == "Filled" or (filled > 0 and remaining <= 0):
        return "filled"
    if filled > 0 and remaining > 0:
        return "partially_filled"
    if status in {"Cancelled", "ApiCancelled"}:
        return "cancelled"
    if status == "Inactive":
        return "rejected_or_inactive"
    if status in {"PendingSubmit", "PreSubmitted", "Submitted", "PendingCancel"}:
        return "active"
    return "unknown"


def _marketable_buy_limit_price(
    reference_price: float, configured_limit: float | None, settings: Settings
) -> float:
    base_price = max(reference_price, configured_limit or 0.0)
    adjusted = base_price * (
        1.0 + max(0.0, settings.entry_order_price_offset_bps) / 10_000.0
    )
    return math.ceil(adjusted * 100.0) / 100.0


def _is_market_hours(
    now: datetime | None = None, session: MarketSession | None = None
) -> bool:
    now = now or datetime.now(NEW_YORK)
    if session is not None:
        return session.opens_at <= now < session.closes_at
    current = now.timetz().replace(tzinfo=None)
    return now.weekday() < 5 and time(9, 30) <= current < time(16, 0)


def _should_flatten(
    settings: Settings,
    now: datetime | None = None,
    session: MarketSession | None = None,
) -> bool:
    now = now or datetime.now(NEW_YORK)
    close = (
        session.closes_at
        if session is not None
        else datetime.combine(now.date(), time(16, 0), tzinfo=NEW_YORK)
    )
    cutoff = close - timedelta(minutes=max(0, settings.flatten_before_close_minutes))
    return now.weekday() < 5 and cutoff <= now < close


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


def _normalize_bar_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=NEW_YORK)
    return value.astimezone(NEW_YORK)


def _fresh_historical_bars(
    broker: IbkrBroker,
    settings: Settings,
    symbol: str,
    *,
    duration: str = "1 D",
    bar_size: str = "1 min",
    what_to_show: str = "TRADES",
    session_only: bool = False,
    completed_only: bool = False,
    session: MarketSession | None = None,
    now: datetime | None = None,
    exchange: str = "SMART",
) -> list[Bar]:
    bars = broker.historical_bars(
        symbol,
        duration=duration,
        bar_size=bar_size,
        what_to_show=what_to_show,
        exchange=exchange,
    )
    return _validate_historical_bars(
        bars,
        settings,
        symbol,
        bar_size=bar_size,
        session_only=session_only,
        completed_only=completed_only,
        session=session,
        now=now,
    )


def _validate_historical_bars(
    bars: list[Bar],
    settings: Settings,
    symbol: str,
    *,
    bar_size: str,
    session_only: bool,
    completed_only: bool,
    session: MarketSession | None,
    now: datetime | None,
) -> list[Bar]:
    now = now or datetime.now(NEW_YORK)
    if session_only:
        session_open = session.opens_at if session is not None else None
        session_close = session.closes_at if session is not None else None
        bars = [
            bar
            for bar in bars
            if (normalized := _normalize_bar_time(bar.time)).date() == now.date()
            and (
                session_open <= normalized < session_close
                if session_open is not None and session_close is not None
                else time(9, 30)
                <= normalized.timetz().replace(tzinfo=None)
                < time(16, 0)
            )
        ]
    if settings.is_live:
        if not bars:
            raise BrokerError(f"no live bars returned for {symbol}")

        last_bar_time = _normalize_bar_time(bars[-1].time)
        age_seconds = (now - last_bar_time).total_seconds()
        max_age_seconds = max(
            settings.live_bar_max_age_seconds, _bar_size_seconds(bar_size) + 120
        )
        if age_seconds < -60:
            raise BrokerError(
                f"latest bar for {symbol} is in the future: {last_bar_time.isoformat()}"
            )
        if age_seconds > max_age_seconds:
            age_minutes = age_seconds / 60
            max_minutes = max_age_seconds / 60
            raise BrokerError(
                f"latest bar for {symbol} is stale: {last_bar_time.isoformat()} "
                f"({age_minutes:.1f} min old; max {max_minutes:.1f}); refusing delayed data"
            )

    if completed_only:
        bar_duration = timedelta(seconds=_bar_size_seconds(bar_size))
        bars = [
            bar
            for bar in bars
            if _normalize_bar_time(bar.time) + bar_duration <= now
        ]
    return bars


def _strategy_quote(
    broker: IbkrBroker,
    settings: Settings,
    symbol: str,
    *,
    exchange: str = "SMART",
):
    if settings.is_live:
        return broker.live_quote(symbol, exchange=exchange)
    return broker.quote(symbol, exchange=exchange)


def _has_price_scale_discontinuity(
    quote, bars: list[Bar], *, maximum_ratio: float = 1.8
) -> bool:
    """Catch unadjusted split/reverse-split data before opening a new position."""
    prices = [bar.open for bar in bars] + [bar.close for bar in bars]
    if quote.close is not None:
        prices.append(float(quote.close))
    prices = [price for price in prices if price > 0]
    return bool(prices) and max(prices) / min(prices) >= maximum_ratio


def _entry_state_path(settings: Settings, now: datetime | None = None) -> Path:
    now = now or datetime.now(NEW_YORK)
    state_dir = Path(settings.state_dir).expanduser()
    return state_dir / f"entries-{now.date().isoformat()}.json"


def _orders_state_path(settings: Settings, now: datetime | None = None) -> Path:
    now = now or datetime.now(NEW_YORK)
    state_dir = Path(settings.state_dir).expanduser()
    return state_dir / f"orders-{now.date().isoformat()}.jsonl"


def _live_quote_cache_path(settings: Settings) -> Path:
    if settings.live_quote_cache_path:
        return Path(settings.live_quote_cache_path).expanduser()
    return Path(settings.state_dir).expanduser() / "live-quotes.json"


def _live_context_cache_path(settings: Settings) -> Path:
    if settings.live_context_cache_path:
        return Path(settings.live_context_cache_path).expanduser()
    return Path(settings.state_dir).expanduser() / "live-context.json"


def _cached_or_broker_market_session(
    broker: IbkrBroker,
    settings: Settings,
    symbol: str,
    now: datetime,
) -> MarketSession | None:
    if settings.is_live:
        try:
            session = load_cached_market_session(
                _live_context_cache_path(settings),
                session_date=now.date(),
                max_age_seconds=settings.live_context_cache_max_age_seconds,
                now=now,
            )
            print("market_session_source=cache", file=sys.stderr)
            return session
        except MarketContextCacheError as exc:
            print(
                f"market_session_source=broker cache_reason={exc}",
                file=sys.stderr,
            )
    return broker.market_session(symbol, now.date())


def _cached_or_snapshot_live_quotes(
    broker: IbkrBroker,
    settings: Settings,
    symbols: tuple[str, ...],
) -> dict[str, Quote]:
    try:
        quotes = load_fresh_quotes(
            _live_quote_cache_path(settings),
            symbols,
            max_age_seconds=settings.live_quote_cache_max_age_seconds,
        )
        print("live_quote_source=cache", file=sys.stderr)
        return quotes
    except QuoteCacheError as exc:
        print(
            f"live_quote_source=snapshot cache_reason={exc}",
            file=sys.stderr,
        )
        return broker.live_quote_snapshots(symbols, exchange="SMART")


def _quote_timing_fields(quote: Quote, now: datetime) -> dict[str, object]:
    age_ms: float | None = None
    if quote.observed_at:
        try:
            observed_at = datetime.fromisoformat(quote.observed_at)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            age_ms = max(
                0.0,
                (now.astimezone(timezone.utc) - observed_at).total_seconds(),
            ) * 1000
        except ValueError:
            age_ms = None
    return {
        "quote_market_time": quote.market_time,
        "quote_received_at": quote.received_at,
        "quote_observed_at": quote.observed_at,
        "quote_published_at": quote.published_at,
        "quote_age_ms": None if age_ms is None else round(age_ms, 1),
    }


def _latest_trade_price_fields(quote: Quote) -> dict[str, object]:
    try:
        latest = float(quote.last) if quote.last is not None else None
    except (TypeError, ValueError):
        latest = None
    if latest is None or not math.isfinite(latest) or latest <= 0:
        return {
            "latest_trade_price": None,
            "latest_trade_price_available": False,
        }
    return {
        "latest_trade_price": round(latest, 4),
        "latest_trade_price_available": True,
    }


def _benchmark_quote_summary(
    symbol: str,
    quote: Quote,
    market_data_exchange: str,
    now: datetime,
) -> dict[str, object]:
    return {
        "role": "benchmark",
        "symbol": symbol,
        "reference_price": round(quote.reference_price, 2),
        **_latest_trade_price_fields(quote),
        "market_data_exchange": market_data_exchange,
        "bar_data_exchange": market_data_exchange,
        "quote_data_exchange": "SMART",
        **_quote_timing_fields(quote, now),
    }


def _protective_order_display(
    broker: IbkrBroker,
    strategy: IntradayMomentumStrategy | SemiconductorRotationStrategy,
    symbol: str,
    position_row: dict[str, str] | None,
    bars: list[Bar],
    now: datetime,
) -> dict[str, object]:
    display: dict[str, object] = {
        "position_status": "holding" if position_row is not None else "flat",
        "stop_loss_pct": strategy.stop_loss_pct_for(symbol),
        "take_profit_pct": strategy.take_profit_pct_for(symbol),
        "calculated_stop_price": None,
        "calculated_take_price": None,
        "active_stop_price": None,
        "active_take_price": None,
        "protection_status": "not_applicable",
    }
    if position_row is None:
        return display

    quantity = int(float(position_row["position"]))
    average_cost = float(position_row["avgCost"])
    stop_price, take_price = strategy.protective_prices(
        symbol, average_cost, bars
    )
    display["calculated_stop_price"] = round(stop_price, 4)
    display["calculated_take_price"] = round(take_price, 4)

    order_ref_prefix = f"momentum-{now.date()}-{symbol}-protect"
    matched = []
    for trade in broker.active_trades_for(symbol, "SELL"):
        order = getattr(trade, "order", None)
        order_ref = str(getattr(order, "orderRef", "") or "")
        if order_ref.startswith(order_ref_prefix):
            matched.append(trade)
            order_type = str(getattr(order, "orderType", "") or "").upper()
            if order_type == "STP":
                value = float(getattr(order, "auxPrice", 0) or 0)
                if value > 0:
                    display["active_stop_price"] = round(value, 4)
            elif order_type == "LMT":
                value = float(getattr(order, "lmtPrice", 0) or 0)
                if value > 0:
                    display["active_take_price"] = round(value, 4)

    if broker.protective_oca_is_complete(
        symbol, quantity, order_ref_prefix=order_ref_prefix
    ):
        display["protection_status"] = "complete"
    elif matched:
        display["protection_status"] = "incomplete"
    else:
        display["protection_status"] = "missing"
    return display


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _load_entry_state(
    settings: Settings, now: datetime | None = None
) -> dict[str, object]:
    path = _entry_state_path(settings, now)
    if not path.exists():
        return {"entry_count": 0, "entries": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"entry_count": 0, "entries": []}
    if not isinstance(data, dict):
        return {"entry_count": 0, "entries": []}
    data.setdefault("entry_count", 0)
    data.setdefault("entries", [])
    return data


def _daily_entry_count(settings: Settings, now: datetime | None = None) -> int:
    state = _load_entry_state(settings, now)
    try:
        return int(state.get("entry_count", 0))
    except (TypeError, ValueError):
        return 0


def _daily_entry_limit_reached(settings: Settings, now: datetime | None = None) -> bool:
    if settings.max_daily_entries <= 0:
        return False
    return _daily_entry_count(settings, now) >= settings.max_daily_entries


def _market_data_exchange_state_path(
    settings: Settings, now: datetime | None = None
) -> Path:
    now = now or datetime.now(NEW_YORK)
    return (
        Path(settings.state_dir).expanduser()
        / f"market-data-source-{now.date().isoformat()}.json"
    )


def _load_market_data_exchange(
    settings: Settings, now: datetime | None = None
) -> str | None:
    path = _market_data_exchange_state_path(settings, now)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BrokerError(f"invalid market-data source state: {path}") from exc
    exchange = str(
        payload.get("bar_exchange", payload.get("exchange", ""))
    ).upper()
    if exchange not in {"SMART", "ARCA"}:
        raise BrokerError(f"invalid pinned market-data exchange: {exchange!r}")
    return exchange


def _record_market_data_exchange(
    settings: Settings,
    exchange: str,
    *,
    reason: str,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(NEW_YORK)
    normalized = exchange.upper()
    if normalized not in {"SMART", "ARCA"}:
        raise ValueError(f"unsupported market-data exchange: {exchange}")
    path = _market_data_exchange_state_path(settings, now)
    _write_text_atomic(
        path,
        json.dumps(
            {
                # Keep exchange for compatibility with the first source-pin
                # format. It has always represented the historical-bar source.
                "exchange": normalized,
                "bar_exchange": normalized,
                "quote_exchange": "SMART",
                "reason": reason,
                "recorded_at": now.isoformat(),
                "session_date": now.date().isoformat(),
            },
            indent=2,
            sort_keys=True,
        ),
    )


def _write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _load_intraday_market_data(
    broker: IbkrBroker,
    settings: Settings,
    strategy: IntradayMomentumStrategy,
    session: MarketSession,
    now: datetime,
) -> tuple[str, dict[str, list[Bar]], dict[str, Quote]]:
    """Pin one bar source for all symbols while keeping quotes on SMART."""

    symbols = tuple(
        dict.fromkeys((strategy.benchmark_symbol, *strategy.symbols))
    )
    pinned = _load_market_data_exchange(settings, now)
    if pinned == "ARCA" and not settings.arca_fallback_enabled:
        raise BrokerError("ARCA market-data source is pinned but fallback is disabled")

    if pinned is not None:
        exchanges = (pinned,)
    elif _daily_entry_count(settings, now) > 0:
        # Older versions did not persist the source. An existing automated
        # entry was generated from SMART, so do not change source mid-session.
        exchanges = ("SMART",)
    elif settings.arca_fallback_enabled:
        exchanges = ("SMART", "ARCA")
    else:
        exchanges = ("SMART",)

    try:
        if settings.is_live:
            quotes_by_symbol = _cached_or_snapshot_live_quotes(
                broker, settings, symbols
            )
        else:
            quotes_by_symbol = {
                symbol: _strategy_quote(
                    broker, settings, symbol, exchange="SMART"
                )
                for symbol in symbols
            }
    except BrokerError as exc:
        raise BrokerError(
            f"complete SMART live quote group unavailable: {exc}"
        ) from exc

    failures: list[str] = []
    for exchange in exchanges:
        try:
            cached_bars = None
            if settings.is_live and exchange == "SMART":
                try:
                    cached_bars = load_fresh_cached_bars(
                        _live_context_cache_path(settings),
                        symbols,
                        session_date=now.date(),
                        source=exchange,
                        bar_size="5 mins",
                        max_age_seconds=settings.live_context_cache_max_age_seconds,
                        now=now,
                    )
                    print("live_bar_source=cache", file=sys.stderr)
                except MarketContextCacheError as exc:
                    print(
                        f"live_bar_source=broker cache_reason={exc}",
                        file=sys.stderr,
                    )
            if cached_bars is not None:
                bars_by_symbol = {
                    symbol: _validate_historical_bars(
                        cached_bars[symbol],
                        settings,
                        symbol,
                        bar_size="5 mins",
                        session_only=True,
                        completed_only=True,
                        session=session,
                        now=now,
                    )
                    for symbol in symbols
                }
            else:
                bars_by_symbol = {
                    symbol: _fresh_historical_bars(
                        broker,
                        settings,
                        symbol,
                        bar_size="5 mins",
                        session_only=True,
                        completed_only=True,
                        session=session,
                        now=now,
                        exchange=exchange,
                    )
                    for symbol in symbols
                }
        except BrokerError as exc:
            failures.append(f"{exchange}: {exc}")
            if pinned is not None:
                break
            continue

        if pinned is None:
            reason = (
                "all strategy symbols passed SMART validation"
                if exchange == "SMART"
                else f"SMART bar validation failed; all symbols passed ARCA: {failures[0]}"
            )
            _record_market_data_exchange(
                settings, exchange, reason=reason, now=now
            )
        return exchange, bars_by_symbol, quotes_by_symbol

    detail = "; ".join(failures) or "no exchange attempted"
    raise BrokerError(f"no complete single-source intraday market data: {detail}")


def _record_daily_entry(
    settings: Settings,
    request: TradeRequest,
    now: datetime | None = None,
    filled_quantity: float | None = None,
    average_fill_price: float | None = None,
    strategy_version: str | None = None,
) -> None:
    now = now or datetime.now(NEW_YORK)
    path = _entry_state_path(settings, now)
    state = _load_entry_state(settings, now)
    entries = state.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    entries.append(
        {
            "time": now.isoformat(),
            "symbol": request.symbol.upper(),
            "quantity": request.quantity,
            "filled_quantity": filled_quantity,
            "average_fill_price": average_fill_price,
            "strategy_version": strategy_version,
            "order_type": request.order_type,
            "limit_price": request.limit_price,
            "time_in_force": request.time_in_force,
            "order_ref": request.order_ref,
            "reduce_only": request.reduce_only,
        }
    )
    state["entry_count"] = _daily_entry_count(settings, now) + 1
    state["entries"] = entries
    _write_text_atomic(path, json.dumps(state, indent=2, sort_keys=True))


def _latest_entry_time(
    settings: Settings, symbol: str, now: datetime | None = None
) -> datetime | None:
    now = now or datetime.now(NEW_YORK)
    entries = _load_entry_state(settings, now).get("entries", [])
    if not isinstance(entries, list):
        return None
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("symbol", "")).upper() != symbol.upper():
            continue
        try:
            timestamp = datetime.fromisoformat(str(entry["time"]))
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=NEW_YORK)
        return timestamp.astimezone(NEW_YORK)
    return None


def _completed_bars_since_entry(
    bars: list[Bar], entry_time: datetime, now: datetime, *, bar_minutes: int = 5
) -> list[Bar]:
    entry_time = entry_time.astimezone(NEW_YORK)
    entry_bar_start = entry_time.replace(
        minute=(entry_time.minute // bar_minutes) * bar_minutes,
        second=0,
        microsecond=0,
    )
    completed: list[Bar] = []
    for bar in bars:
        bar_time = _normalize_bar_time(bar.time)
        if bar_time < entry_bar_start:
            continue
        if bar_time + timedelta(minutes=bar_minutes) > now:
            continue
        completed.append(bar)
    return completed


def _record_order_state(
    settings: Settings, request: TradeRequest, trade, now: datetime | None = None
) -> None:
    now = now or datetime.now(NEW_YORK)
    order = getattr(trade, "order", None)
    order_status = getattr(trade, "orderStatus", None)
    fills = getattr(trade, "fills", [])
    log = getattr(trade, "log", [])
    record = {
        "recorded_at": now.isoformat(),
        "request": {
            "symbol": request.symbol.upper(),
            "action": request.action.upper(),
            "quantity": request.quantity,
            "order_type": request.order_type,
            "limit_price": request.limit_price,
            "time_in_force": request.time_in_force,
            "order_ref": request.order_ref,
            "reduce_only": request.reduce_only,
        },
        "order": {
            "order_id": getattr(order, "orderId", None),
            "perm_id": getattr(order, "permId", None),
            "client_id": getattr(order, "clientId", None),
            "action": getattr(order, "action", None),
            "total_quantity": getattr(order, "totalQuantity", None),
            "order_type": getattr(order, "orderType", None),
            "limit_price": getattr(order, "lmtPrice", None),
            "time_in_force": getattr(order, "tif", None),
            "account": getattr(order, "account", None),
            "order_ref": getattr(order, "orderRef", None),
            "oca_group": getattr(order, "ocaGroup", None),
        },
        "status": {
            "lifecycle": _trade_lifecycle(trade),
            "status": getattr(order_status, "status", None),
            "filled": getattr(order_status, "filled", None),
            "remaining": getattr(order_status, "remaining", None),
            "avg_fill_price": getattr(order_status, "avgFillPrice", None),
            "last_fill_price": getattr(order_status, "lastFillPrice", None),
            "why_held": getattr(order_status, "whyHeld", None),
        },
        "fills": _json_safe(fills),
        "log": _json_safe(log),
    }
    path = _orders_state_path(settings, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as file:
        file.write(json.dumps(record, sort_keys=True))
        file.write("\n")


def _parse_position_rows(
    rows: list[dict[str, str]], symbols: tuple[str, ...]
) -> dict[str, dict[str, str]]:
    tracked = {symbol.upper() for symbol in symbols}
    positions: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in tracked:
            continue
        try:
            quantity = float(row.get("position", "0"))
        except ValueError:
            continue
        if quantity == 0:
            continue
        positions[symbol] = row
    return positions


def _validate_strategy_positions(
    positions: dict[str, dict[str, str]],
) -> None:
    for symbol, position_row in positions.items():
        position = float(position_row["position"])
        if not math.isclose(position, round(position), abs_tol=1e-6):
            raise BrokerError(
                f"fractional {symbol} strategy position {position:g}; "
                "possible corporate action; refusing automation"
            )


def _ensure_protective_oca(
    broker: IbkrBroker,
    settings: Settings,
    strategy: IntradayMomentumStrategy | SemiconductorRotationStrategy,
    symbol: str,
    position_row: dict[str, str],
    bars: list[Bar],
    now: datetime,
) -> str:
    quantity = int(float(position_row["position"]))
    average_cost = float(position_row["avgCost"])
    order_ref_prefix = f"momentum-{now.date()}-{symbol}-protect"
    if broker.protective_oca_is_complete(
        symbol, quantity, order_ref_prefix=order_ref_prefix
    ):
        return "complete"

    active_sells = broker.active_trades_for(symbol, "SELL")
    incomplete_strategy_orders = []
    conflicting_orders = []
    for trade in active_sells:
        order = getattr(trade, "order", None)
        order_ref = str(getattr(order, "orderRef", "") or "")
        if order_ref.startswith(order_ref_prefix) or (
            order_ref.startswith("momentum-") and "-protect-" in order_ref
        ):
            incomplete_strategy_orders.append(trade)
        else:
            conflicting_orders.append(trade)
    if conflicting_orders:
        raise BrokerError(
            f"active non-protective SELL order exists for {symbol}; "
            "refusing to replace protection"
        )

    for trade in incomplete_strategy_orders:
        broker.cancel_order(trade)
        order = getattr(trade, "order", None)
        _record_order_state(
            settings,
            TradeRequest(
                symbol=symbol,
                action="SELL",
                quantity=quantity,
                order_type=str(getattr(order, "orderType", "MKT") or "MKT"),
                limit_price=getattr(order, "lmtPrice", None),
                time_in_force=str(getattr(order, "tif", "GTC") or "GTC"),
                order_ref=str(getattr(order, "orderRef", "") or ""),
                reduce_only=True,
            ),
            trade,
            now,
        )
    if broker.active_order_quantity(symbol, "SELL") > 0:
        raise BrokerError(
            f"incomplete protective SELL cancellation unresolved for {symbol}"
        )

    stop_price, take_price = strategy.protective_prices(
        symbol, average_cost, bars
    )
    trades = broker.place_protective_oca(
        symbol,
        quantity,
        stop_price,
        take_price,
        order_ref=order_ref_prefix,
    )
    for order_type, trade, price in (
        ("STP", trades[0], stop_price),
        ("LMT", trades[1], take_price),
    ):
        _record_order_state(
            settings,
            TradeRequest(
                symbol=symbol,
                action="SELL",
                quantity=quantity,
                order_type=order_type,
                limit_price=price if order_type == "LMT" else None,
                time_in_force="GTC",
                reduce_only=True,
            ),
            trade,
            now,
        )
    return "recreated" if incomplete_strategy_orders else "created"


def _flatten_strategy_positions_if_due(
    broker: IbkrBroker,
    settings: Settings,
    strategy: IntradayMomentumStrategy | SemiconductorRotationStrategy,
    now: datetime,
    session: MarketSession,
) -> bool:
    if not _should_flatten(settings, now, session):
        return False
    current_positions = _parse_position_rows(broker.positions(), strategy.symbols)
    _validate_strategy_positions(current_positions)
    if not current_positions:
        print("mandatory flatten window: no strategy position")
        return True

    for symbol, position_row in current_positions.items():
        quantity = int(float(position_row["position"]))
        cancelled = []
        for trade in broker.active_trades_for(symbol, "SELL"):
            order_ref = str(
                getattr(getattr(trade, "order", None), "orderRef", "") or ""
            )
            if order_ref.startswith("momentum-") and "-protect-" in order_ref:
                broker.cancel_order(trade)
                cancelled.append(trade)
        for trade in cancelled:
            _record_order_state(
                settings,
                TradeRequest(
                    symbol=symbol,
                    action="SELL",
                    quantity=quantity,
                    reduce_only=True,
                ),
                trade,
                now,
            )
        request = TradeRequest(
            symbol=symbol,
            action="SELL",
            quantity=quantity,
            order_ref=f"momentum-{now.date()}-{symbol}-eod-exit",
            reduce_only=True,
        )
        risk_settings = replace(
            settings,
            allowed_symbols=strategy.symbols,
            max_order_notional=strategy.max_notional,
        )
        risk_decision = RiskManager(risk_settings).validate(
            request,
            0.0,
            position_quantity=float(position_row["position"]),
            pending_sell_quantity=broker.active_order_quantity(symbol, "SELL"),
        )
        print(risk_decision.reason)
        if risk_decision.allowed:
            _submit_or_print(
                broker,
                settings,
                request,
                f"mandatory end-of-day flatten: {symbol} qty={quantity}",
            )
    return True


def _momentum_kwargs(args: argparse.Namespace) -> dict[str, object]:
    profile = getattr(args, "profile", "balanced")
    if profile == "high-frequency":
        return {
            "fast_window": 10,
            "slow_window": 18,
            "trend_window": 24,
            "trend_lookback": 5,
            "min_bars": 20,
            "stop_loss_pct": args.stop_loss_pct,
            "take_profit_pct": args.take_profit_pct,
            "min_confirm_bars": 2,
            "min_trend_gap": args.min_trend_gap,
            "min_vwap_gap": args.min_vwap_gap,
            "min_score": args.min_score,
        }
    return {
        "fast_window": args.fast,
        "slow_window": args.slow,
        "trend_window": args.trend_window,
        "trend_lookback": args.trend_lookback,
        "min_bars": args.min_bars,
        "stop_loss_pct": args.stop_loss_pct,
        "take_profit_pct": args.take_profit_pct,
        "min_confirm_bars": args.min_confirm_bars,
        "min_trend_gap": args.min_trend_gap,
        "min_vwap_gap": args.min_vwap_gap,
        "min_score": args.min_score,
    }


def _build_momentum_strategy(args: argparse.Namespace, settings: Settings):
    profile = getattr(args, "profile", "balanced")
    if profile in {
        "rotation",
        "rotation-hysteresis",
        "rotation-hysteresis-v1",
        "rotation-hysteresis-v2",
    }:
        hysteresis = profile != "rotation"
        if hysteresis:
            benchmark_symbol = str(args.benchmark_symbol).upper()
            if benchmark_symbol != FROZEN_ROTATION_HYSTERESIS_PARAMETERS["benchmark_symbol"]:
                raise ValueError(
                    f"{profile} freezes benchmark_symbol=QQQ; "
                    "create a new candidate profile instead of overriding the baseline"
                )
            parameters = (
                ROTATION_HYSTERESIS_V2_PARAMETERS
                if profile == ROTATION_HYSTERESIS_V2_VERSION
                else FROZEN_ROTATION_HYSTERESIS_PARAMETERS
            )
            return SemiconductorRotationStrategy(
                **parameters,
                max_notional=args.max_notional or settings.max_order_notional,
                max_risk_per_trade=settings.max_risk_per_trade,
            )
        return SemiconductorRotationStrategy(
            benchmark_symbol=args.benchmark_symbol,
            max_notional=args.max_notional or settings.max_order_notional,
            max_risk_per_trade=settings.max_risk_per_trade,
            atr_window=settings.atr_window,
            atr_stop_multiple=settings.atr_stop_multiple,
            long_stop_loss_pct=0.012,
            short_stop_loss_pct=0.012,
            long_take_profit_pct=0.035,
            short_take_profit_pct=0.035,
            use_exit_hysteresis=False,
            exit_confirm_bars=3,
            benchmark_exit_confirm_bars=1,
            exit_reversal_votes=2,
        )
    return IntradayMomentumStrategy(
        symbols=settings.vwap_symbols,
        benchmark_symbol=args.benchmark_symbol,
        max_notional=args.max_notional or settings.max_order_notional,
        max_risk_per_trade=settings.max_risk_per_trade,
        atr_window=settings.atr_window,
        atr_stop_multiple=settings.atr_stop_multiple,
        **_momentum_kwargs(args),
        require_benchmark_confirmation=not args.no_benchmark_confirmation,
        require_vwap_confirmation=not args.no_vwap_confirmation,
    )


def _run_live_quote_cache(settings: Settings, args: argparse.Namespace) -> int:
    if not settings.readonly or not settings.dry_run:
        raise BrokerError(
            "stream-live-quotes requires IBKR_READONLY=true and IBKR_DRY_RUN=true"
        )
    if settings.allow_live_trading:
        raise BrokerError(
            "stream-live-quotes requires IBKR_ALLOW_LIVE_TRADING=false"
        )
    symbols = tuple(
        dict.fromkeys(item.strip().upper() for item in args.symbols if item.strip())
    )
    cache_path = (
        Path(args.cache_path).expanduser()
        if args.cache_path
        else _live_quote_cache_path(settings)
    )
    writer = QuoteCacheWriter(
        cache_path,
        symbols,
        max_samples_per_symbol=settings.live_quote_max_samples_per_symbol,
        refresh_seconds=settings.live_quote_cache_refresh_seconds,
    )
    print(
        json.dumps(
            {
                "cache_path": str(cache_path),
                "max_samples_per_symbol": settings.live_quote_max_samples_per_symbol,
                "refresh_seconds": settings.live_quote_cache_refresh_seconds,
                "symbols": symbols,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    while True:
        broker = IbkrBroker(settings)
        try:
            broker.connect()
            broker.stream_live_quotes(
                symbols,
                lambda quotes, market_times, received_times, observed_at: writer.update(
                    quotes,
                    market_times=market_times,
                    received_times=received_times,
                    observed_at=observed_at,
                ),
                exchange="SMART",
            )
        except KeyboardInterrupt:
            return 0
        except (BrokerError, ConnectionError, TimeoutError, OSError) as exc:
            print(
                f"live quote stream reconnecting after {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        finally:
            broker.disconnect()
        try:
            blocking_sleep(5)
        except KeyboardInterrupt:
            return 0


def _run_live_context_cache(settings: Settings, args: argparse.Namespace) -> int:
    if not settings.readonly or not settings.dry_run:
        raise BrokerError(
            "cache-live-context requires IBKR_READONLY=true and IBKR_DRY_RUN=true"
        )
    if settings.allow_live_trading:
        raise BrokerError(
            "cache-live-context requires IBKR_ALLOW_LIVE_TRADING=false"
        )
    symbols = tuple(
        dict.fromkeys(item.strip().upper() for item in args.symbols if item.strip())
    )
    if not symbols:
        raise ValueError("cache-live-context requires at least one symbol")
    cache_path = (
        Path(args.cache_path).expanduser()
        if args.cache_path
        else _live_context_cache_path(settings)
    )
    last_refresh_bucket: tuple[object, ...] | None = None
    cached_session_date = None
    cached_session: MarketSession | None = None
    while True:
        broker = IbkrBroker(settings)
        try:
            broker.connect()
            while True:
                now = datetime.now(NEW_YORK)
                refresh_bucket = (
                    now.date(),
                    now.hour,
                    now.minute // 5,
                )
                if refresh_bucket != last_refresh_bucket:
                    if cached_session_date != now.date():
                        cached_session = broker.market_session(symbols[0], now.date())
                        cached_session_date = now.date()
                    session = cached_session
                    bars_by_symbol: dict[str, list[Bar]] = {}
                    if session is not None and _is_market_hours(now, session):
                        bars_by_symbol = {
                            symbol: _fresh_historical_bars(
                                broker,
                                settings,
                                symbol,
                                bar_size="5 mins",
                                session_only=True,
                                completed_only=True,
                                session=session,
                                now=now,
                                exchange="SMART",
                            )
                            for symbol in symbols
                        }
                    write_market_context_cache(
                        cache_path,
                        session_date=now.date(),
                        session=session,
                        bars_by_symbol=bars_by_symbol,
                        source="SMART",
                        bar_size="5 mins",
                    )
                    last_refresh_bucket = refresh_bucket
                    print(
                        json.dumps(
                            {
                                "bar_counts": {
                                    symbol: len(bars_by_symbol.get(symbol, []))
                                    for symbol in symbols
                                },
                                "cache_path": str(cache_path),
                                "session_date": now.date().isoformat(),
                                "source": "SMART",
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                blocking_sleep(1)
        except KeyboardInterrupt:
            return 0
        except (BrokerError, ConnectionError, TimeoutError, OSError) as exc:
            print(
                f"live context cache reconnecting after {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        finally:
            broker.disconnect()
        try:
            blocking_sleep(5)
        except KeyboardInterrupt:
            return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()

    if args.command == "doctor":
        return _doctor(settings)

    if args.command == "stream-live-quotes":
        return _run_live_quote_cache(settings, args)

    if args.command == "cache-live-context":
        return _run_live_context_cache(settings, args)

    broker = None
    if not (args.command == "backtest-momentum" and args.reuse_data):
        broker = _with_broker(settings)
    try:
        if args.command == "heartbeat":
            print(broker.server_time().isoformat())
            return 0

        if args.command == "refresh-history":
            if not settings.readonly or not settings.dry_run:
                raise BrokerError(
                    "refresh-history requires IBKR_READONLY=true and IBKR_DRY_RUN=true"
                )
            if settings.allow_live_trading:
                raise BrokerError(
                    "refresh-history requires IBKR_ALLOW_LIVE_TRADING=false"
                )
            broker.server_time()
            now = datetime.now(timezone.utc)
            symbols = tuple(dict.fromkeys(item.upper() for item in args.symbols))
            fetched_counts: dict[str, int] = {}
            for symbol in symbols:
                rows = broker.historical_bars_paged(
                    symbol,
                    args.duration,
                    bar_size=args.bar_size,
                    what_to_show="TRADES",
                    end_time=now,
                    page_callback=lambda page, cached_symbol=symbol: save_bars_by_day(
                        args.data_dir,
                        cached_symbol,
                        args.bar_size,
                        page,
                        exchange=args.market_data_exchange,
                    ),
                    exchange=args.market_data_exchange,
                )
                fetched_counts[symbol] = len(rows)

            sessions = broker.historical_market_sessions(
                "QQQ",
                # This schedule is only used to validate the newest cached
                # sessions. Requesting a 730-day schedule as "730 D" is
                # rejected by IBKR because durations over 365 days must use
                # year units, and the old history is irrelevant here.
                num_days=schedule_lookback_days(args.recent_sessions),
                end_datetime=now,
            )
            cached = {
                symbol: load_bars(args.data_dir, symbol, args.bar_size)
                for symbol in symbols
            }
            validation = validate_recent_cached_sessions(
                cached,
                sessions,
                now=now,
                recent_sessions=args.recent_sessions,
            )
            print(
                json.dumps(
                    {"fetched_counts": fetched_counts, "validation": validation},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "quote":
            print(
                json.dumps(asdict(broker.quote(args.symbol)), indent=2, sort_keys=True)
            )
            return 0

        if args.command == "account":
            rows = broker.account_summary()
            print(format_table(rows, ["account", "tag", "value", "currency"]))
            return 0

        if args.command == "balance":
            rows = broker.balance()
            print(format_table(rows, ["account", "tag", "value", "currency"]))
            return 0

        if args.command == "positions":
            rows = broker.positions()
            print(
                format_table(
                    rows,
                    [
                        "account",
                        "symbol",
                        "secType",
                        "exchange",
                        "currency",
                        "position",
                        "avgCost",
                    ],
                )
            )
            return 0

        if args.command == "order":
            is_sell = args.action.upper() == "SELL"
            request = TradeRequest(
                symbol=args.symbol.upper(),
                action=args.action.upper(),
                quantity=args.quantity,
                order_type=args.type,
                limit_price=args.limit_price,
                order_ref=f"manual-{datetime.now(NEW_YORK).strftime('%Y%m%d%H%M%S')}",
                reduce_only=is_sell,
            )
            reference_price = args.reference_price
            if reference_price is None:
                reference_price = (
                    request.limit_price or broker.quote(request.symbol).reference_price
                )
            position_quantity = (
                broker.position_quantity(request.symbol) if is_sell else None
            )
            pending_sell_quantity = (
                broker.active_order_quantity(request.symbol, "SELL") if is_sell else 0.0
            )
            decision = RiskManager(settings).validate(
                request,
                reference_price,
                position_quantity=position_quantity,
                pending_sell_quantity=pending_sell_quantity,
            )
            print(decision.reason)
            if decision.allowed:
                _submit_or_print(broker, settings, request, decision.reason)
            return 0

        if args.command == "run-once":
            quote = broker.quote(args.symbol)
            bars = broker.historical_bars(args.symbol)
            strategy = MovingAverageStrategy(args.fast, args.slow, args.quantity)
            decision = strategy.decide(args.symbol.upper(), quote, bars)
            print(json.dumps(asdict(decision), indent=2, sort_keys=True))
            if decision.action == "HOLD":
                return 0
            request = TradeRequest(decision.symbol, decision.action, decision.quantity)
            risk_decision = RiskManager(settings).validate(
                request, decision.reference_price
            )
            print(risk_decision.reason)
            if risk_decision.allowed:
                _submit_or_print(broker, settings, request, risk_decision.reason)
            return 0

        if args.command == "vwap-pullback":
            strategy = VwapPullbackStrategy(
                symbols=settings.vwap_symbols,
                max_notional=args.max_notional or settings.max_order_notional,
            )
            now = datetime.now(NEW_YORK)
            session = broker.market_session(strategy.symbols[0], now.date())
            if session is None:
                print("exchange holiday: skipping vwap_pullback scan")
                return 0
            if not _is_market_hours(now, session):
                print("market closed: skipping vwap_pullback scan")
                return 0
            scan_rows: list[dict[str, object]] = []
            signal_decisions: list[tuple[str, object]] = []
            for symbol in strategy.symbols:
                quote = _strategy_quote(broker, settings, symbol)
                bars = _fresh_historical_bars(broker, settings, symbol)
                decision = strategy.decide(symbol, quote, bars)
                scan_rows.append(
                    {
                        "symbol": symbol,
                        "action": decision.action,
                        "quantity": decision.quantity,
                        "reference_price": round(decision.reference_price, 2),
                        "limit_price": None
                        if decision.limit_price is None
                        else round(decision.limit_price, 2),
                        "signal": decision.signal,
                        "reason": decision.reason,
                    }
                )
                if decision.signal:
                    signal_decisions.append((symbol, decision))

            print(json.dumps(scan_rows, indent=2, sort_keys=True))
            if not signal_decisions:
                print("no signal: no order")
                return 0

            # Prefer the strongest gap above VWAP while staying inside the single-order cap.
            symbol, decision = max(
                signal_decisions,
                key=lambda item: (
                    float(item[1].meta.get("close", 0.0))
                    - float(item[1].meta.get("vwap", 0.0))
                ),
            )
            request = TradeRequest(
                symbol=symbol,
                action="BUY",
                quantity=decision.quantity,
                order_type="LMT",
                limit_price=decision.limit_price,
            )
            risk_settings = replace(
                settings,
                allowed_symbols=strategy.symbols,
                max_order_notional=strategy.max_notional,
            )
            risk_decision = RiskManager(risk_settings).validate(
                request, decision.reference_price
            )
            print(risk_decision.reason)
            if risk_decision.allowed:
                _submit_or_print(
                    broker,
                    settings,
                    request,
                    f"auto order candidate: {symbol} qty={decision.quantity} limit={decision.limit_price:.2f}",
                )
            return 0

        if args.command == "intraday-momentum":
            strategy = _build_momentum_strategy(args, settings)
            now = datetime.now(NEW_YORK)
            session = _cached_or_broker_market_session(
                broker, settings, strategy.benchmark_symbol, now
            )
            if session is None:
                print("exchange holiday: skipping intraday_momentum scan")
                return 0
            if not _is_market_hours(now, session):
                print("market closed: skipping intraday_momentum scan")
                return 0
            if _flatten_strategy_positions_if_due(
                broker, settings, strategy, now, session
            ):
                return 0
            (
                market_data_exchange,
                strategy_bars,
                strategy_quotes,
            ) = _load_intraday_market_data(
                broker, settings, strategy, session, now
            )
            benchmark_bars = strategy_bars[strategy.benchmark_symbol]
            benchmark_quote = strategy_quotes[strategy.benchmark_symbol]
            benchmark_summary = _benchmark_quote_summary(
                strategy.benchmark_symbol,
                benchmark_quote,
                market_data_exchange,
                now,
            )

            current_positions = _parse_position_rows(
                broker.positions(), strategy.symbols
            )
            _validate_strategy_positions(current_positions)
            scan_rows: list[dict[str, object]] = []
            decisions: dict[str, object] = {}
            price_scale_discontinuities: set[str] = set()

            for symbol in strategy.symbols:
                quote = strategy_quotes[symbol]
                bars = strategy_bars[symbol]
                if _has_price_scale_discontinuity(quote, bars):
                    price_scale_discontinuities.add(symbol)
                if symbol in current_positions:
                    position_row = current_positions[symbol]
                    quantity = int(float(position_row["position"]))
                    if _should_flatten(settings, now, session):
                        decision = StrategyDecision(
                            symbol=symbol,
                            action="SELL",
                            quantity=quantity,
                            reference_price=quote.reference_price,
                            limit_price=None,
                            reason="mandatory end-of-day flatten window",
                            signal=True,
                            meta={"eod": True, "bars": len(bars)},
                        )
                    else:
                        decision = strategy.exit_decide(
                            symbol,
                            quote,
                            bars,
                            quantity,
                            float(position_row["avgCost"]),
                            benchmark_bars=benchmark_bars,
                        )
                        if (
                            not decision.signal
                            and getattr(strategy, "profit_lock_activation_pct", None)
                            is not None
                        ):
                            entry_time = _latest_entry_time(settings, symbol, now)
                            if entry_time is not None:
                                completed_bars = _completed_bars_since_entry(
                                    bars, entry_time, now
                                )
                                lock_decision = strategy.profit_lock_decide(
                                    symbol,
                                    quote,
                                    completed_bars,
                                    quantity,
                                    float(position_row["avgCost"]),
                                )
                                if lock_decision.signal:
                                    decision = lock_decision
                else:
                    decision = strategy.decide(
                        symbol, quote, bars, benchmark_bars=benchmark_bars
                    )

                decisions[symbol] = decision
                bar_count = len(bars)
                position_row = current_positions.get(symbol)
                protection_display = _protective_order_display(
                    broker,
                    strategy,
                    symbol,
                    position_row,
                    bars,
                    now,
                )
                if position_row is not None:
                    strategy_status = (
                        "exit_candidate"
                        if decision.signal and decision.action == "SELL"
                        else "holding"
                    )
                    order_status = (
                        "exit_candidate_not_submitted_yet"
                        if strategy_status == "exit_candidate"
                        else "protective_orders_active"
                        if protection_display["protection_status"] == "complete"
                        else "protection_requires_attention"
                    )
                else:
                    strategy_status = (
                        "entry_candidate"
                        if decision.signal and decision.action == "BUY"
                        else "flat_no_signal"
                    )
                    order_status = (
                        "entry_candidate_not_submitted_yet"
                        if strategy_status == "entry_candidate"
                        else "no_order_action"
                    )
                scan_rows.append(
                    {
                        "symbol": symbol,
                        "action": decision.action,
                        "entry_status": (
                            "position_open"
                            if position_row is not None
                            else
                            "entry_candidate"
                            if decision.signal and decision.action == "BUY"
                            else "not_entered"
                        ),
                        "strategy_status": strategy_status,
                        "order_status": order_status,
                        "quantity": decision.quantity,
                        "reference_price": round(decision.reference_price, 2),
                        **_latest_trade_price_fields(quote),
                        "limit_price": None
                        if decision.limit_price is None
                        else round(decision.limit_price, 2),
                        "signal": decision.signal,
                        "score": round(float(decision.meta.get("score", 0.0)), 6),
                        "reason": decision.reason,
                        "bar_count": bar_count,
                        "bars_required": strategy.min_bars,
                        "bars_remaining": max(0, strategy.min_bars - bar_count),
                        "fast_ema": (
                            decision.meta.get("fast_ema")
                            if bar_count >= strategy.fast_window
                            else None
                        ),
                        "slow_ema": (
                            decision.meta.get("slow_ema")
                            if bar_count >= strategy.slow_window
                            else None
                        ),
                        "trend_ema": (
                            decision.meta.get("trend_ema")
                            if bar_count >= strategy.trend_window
                            else None
                        ),
                        "market_data_exchange": market_data_exchange,
                        "bar_data_exchange": market_data_exchange,
                        "quote_data_exchange": "SMART",
                        **protection_display,
                        **_quote_timing_fields(quote, now),
                    }
                )

            print(
                json.dumps(
                    {
                        "core_decisions": [
                            {
                                key: row[key]
                                for key in (
                                    "symbol",
                                    "action",
                                    "signal",
                                    "entry_status",
                                    "strategy_status",
                                    "order_status",
                                    "position_status",
                                    "latest_trade_price",
                                    "latest_trade_price_available",
                                    "fast_ema",
                                    "slow_ema",
                                    "stop_loss_pct",
                                    "take_profit_pct",
                                    "calculated_stop_price",
                                    "calculated_take_price",
                                    "active_stop_price",
                                    "active_take_price",
                                    "protection_status",
                                    "bar_count",
                                    "bars_required",
                                    "bars_remaining",
                                    "reason",
                                )
                            }
                            for row in scan_rows
                        ]
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            print(
                json.dumps(
                    {"benchmark_quote": benchmark_summary},
                    indent=2,
                    sort_keys=True,
                )
            )
            print(json.dumps(scan_rows, indent=2, sort_keys=True))

            exit_candidates = [
                decision
                for symbol, decision in decisions.items()
                if symbol in current_positions
                and getattr(decision, "signal", False)
                and decision.action == "SELL"
            ]
            if exit_candidates:
                decision = exit_candidates[0]
                position_quantity = float(
                    current_positions[decision.symbol]["position"]
                )
                # Protective OCA legs are SELL orders too. Cancel them and wait
                # for acknowledgement before submitting the software exit.
                cancelled = broker.cancel_active_orders(
                    decision.symbol,
                    "SELL",
                    order_ref_prefix=f"momentum-{datetime.now(NEW_YORK).date()}-{decision.symbol}-protect",
                )
                for trade in cancelled:
                    _record_order_state(
                        settings,
                        TradeRequest(
                            symbol=decision.symbol,
                            action="SELL",
                            quantity=int(position_quantity),
                            reduce_only=True,
                        ),
                        trade,
                    )
                request = TradeRequest(
                    symbol=decision.symbol,
                    action="SELL",
                    quantity=int(position_quantity),
                    order_ref=f"momentum-{datetime.now(NEW_YORK).date()}-{decision.symbol}-exit",
                    reduce_only=True,
                )
                risk_settings = replace(
                    settings,
                    allowed_symbols=strategy.symbols,
                    max_order_notional=strategy.max_notional,
                )
                risk_decision = RiskManager(risk_settings).validate(
                    request,
                    decision.reference_price,
                    position_quantity=position_quantity,
                    pending_sell_quantity=broker.active_order_quantity(
                        decision.symbol, "SELL"
                    ),
                )
                print(risk_decision.reason)
                if risk_decision.allowed:
                    _submit_or_print(
                        broker,
                        settings,
                        request,
                        f"exit candidate: {decision.symbol} qty={request.quantity}",
                    )
                return 0

            if current_positions:
                if not settings.readonly and not settings.dry_run:
                    for symbol, position_row in current_positions.items():
                        status = _ensure_protective_oca(
                            broker,
                            settings,
                            strategy,
                            symbol,
                            position_row,
                            strategy_bars[symbol],
                            now,
                        )
                        print(f"protective OCA {symbol}: {status}")
                print("position already aligned: no new entry")
                return 0

            buy_candidates = [
                decision
                for decision in decisions.values()
                if getattr(decision, "signal", False) and decision.action == "BUY"
            ]
            if not buy_candidates:
                print("no signal: no order")
                return 0
            if price_scale_discontinuities:
                print(
                    "possible split/reverse-split or unadjusted price discontinuity for "
                    f"{','.join(sorted(price_scale_discontinuities))}; no new entry"
                )
                return 0
            broker_entry_count = sum(
                broker.filled_order_ref_prefix_count(
                    f"momentum-{now.date()}-{symbol}-entry-"
                )
                for symbol in strategy.symbols
            )
            effective_entry_count = max(
                _daily_entry_count(settings), broker_entry_count
            )
            if settings.is_live and settings.max_daily_entries > 0 and (
                effective_entry_count >= settings.max_daily_entries
            ):
                print(
                    f"daily entry limit reached: "
                    f"{effective_entry_count}/{settings.max_daily_entries}; "
                    "no new entry"
                )
                return 0
            if _should_flatten(settings, now, session):
                print("end-of-day flatten window: no new entry")
                return 0
            entry_order_ref = (
                f"momentum-{datetime.now(NEW_YORK).date()}-"
                f"{max(buy_candidates, key=lambda item: float(item.meta.get('score', 0.0))).symbol}-entry-"
                f"{datetime.now(NEW_YORK).strftime('%H%M%S')}"
            )
            if broker.order_ref_exists(entry_order_ref):
                print(
                    f"order ref {entry_order_ref} already exists in IBKR active/completed orders; no replay"
                )
                return 0
            active_buy_quantity = sum(
                broker.active_order_quantity(symbol, "BUY")
                for symbol in strategy.symbols
            )
            if active_buy_quantity > 0:
                print(
                    f"active entry order exists (remaining={active_buy_quantity:g}); no duplicate entry"
                )
                return 0

            decision = max(
                buy_candidates, key=lambda item: float(item.meta.get("score", 0.0))
            )
            limit_price = _marketable_buy_limit_price(
                decision.reference_price, decision.limit_price, settings
            )
            quantity = min(decision.quantity, int(strategy.max_notional // limit_price))
            if quantity <= 0:
                print(
                    f"marketable limit {limit_price:.2f} leaves no quantity within notional cap"
                )
                return 0
            request = TradeRequest(
                symbol=decision.symbol,
                action="BUY",
                quantity=quantity,
                order_type="LMT",
                limit_price=limit_price,
                time_in_force="DAY",
                order_ref=entry_order_ref,
            )
            risk_settings = replace(
                settings,
                allowed_symbols=strategy.symbols,
                max_order_notional=strategy.max_notional,
            )
            risk_decision = RiskManager(risk_settings).validate(request, limit_price)
            print(risk_decision.reason)
            if risk_decision.allowed:
                trade = _submit_or_print(
                    broker,
                    settings,
                    request,
                    f"auto order candidate: {decision.symbol} qty={quantity} limit={limit_price:.2f}",
                )
                if (
                    trade is not None
                    and settings.is_live
                    and not settings.readonly
                    and not settings.dry_run
                ):
                    broker.wait_for_trade_update(
                        trade, settings.entry_order_fill_wait_seconds
                    )
                    _record_order_state(settings, request, trade)
                    filled = _trade_filled_quantity(trade)
                    remaining = _trade_remaining_quantity(trade)
                    if filled <= 0:
                        if remaining > 0:
                            broker.cancel_order(trade)
                            _record_order_state(settings, request, trade)
                        print("entry order not filled; daily entry state not recorded")
                        return 0
                    if remaining > 0:
                        broker.cancel_order(trade)
                        _record_order_state(settings, request, trade)
                        filled = _trade_filled_quantity(trade)
                        remaining = _trade_remaining_quantity(trade)
                    if remaining > 0:
                        raise BrokerError(
                            f"entry cancellation unresolved for {decision.symbol}; refusing to size protection"
                        )
                    filled_quantity = int(filled)
                    average_fill_price = _trade_average_fill_price(trade) or limit_price
                    _record_daily_entry(
                        settings,
                        request,
                        filled_quantity=filled,
                        average_fill_price=average_fill_price,
                        strategy_version=(
                            ROTATION_HYSTERESIS_V2_VERSION
                            if args.profile == ROTATION_HYSTERESIS_V2_VERSION
                            else args.profile
                        ),
                    )
                    print(f"entry filled quantity={filled}; daily entry state recorded")
                    if filled_quantity > 0:
                        bars = strategy_bars[decision.symbol]
                        stop_price, take_price = strategy.protective_prices(
                            decision.symbol, average_fill_price, bars
                        )
                        protective_trades = broker.place_protective_oca(
                            decision.symbol,
                            filled_quantity,
                            stop_price,
                            take_price,
                            order_ref=f"momentum-{datetime.now(NEW_YORK).date()}-{decision.symbol}-protect",
                        )
                        for protective_trade in protective_trades:
                            _record_order_state(
                                settings,
                                TradeRequest(
                                    symbol=decision.symbol,
                                    action="SELL",
                                    quantity=filled_quantity,
                                    time_in_force="GTC",
                                    reduce_only=True,
                                ),
                                protective_trade,
                            )
            return 0

        if args.command == "backtest-momentum":
            strategy = _build_momentum_strategy(args, settings)
            cost_model = BacktestCostModel(
                commission_per_order=args.commission_per_order,
                slippage_bps=args.slippage_bps,
                spread_bps=args.spread_bps,
            )
            if isinstance(strategy, SemiconductorRotationStrategy):
                strategy_report: dict[str, object] = {
                    "benchmark_symbol": strategy.benchmark_symbol,
                    "profile": args.profile,
                    "fast": strategy.fast_window,
                    "slow": strategy.slow_window,
                    "trend_window": strategy.trend_window,
                    "trend_lookback": strategy.trend_lookback,
                    "min_bars": strategy.min_bars,
                    "require_benchmark_confirmation": strategy.require_benchmark_confirmation,
                    "require_vwap_confirmation": strategy.require_vwap_confirmation,
                    "use_exit_hysteresis": strategy.use_exit_hysteresis,
                    "exit_confirm_bars": strategy.exit_confirm_bars,
                    "benchmark_exit_confirm_bars": strategy.benchmark_exit_confirm_bars,
                    "exit_reversal_votes": strategy.exit_reversal_votes,
                    "profit_lock_activation_pct": strategy.profit_lock_activation_pct,
                    "profit_lock_drawdown_pct": strategy.profit_lock_drawdown_pct,
                    "entry_fill_cutoff_et_minutes": strategy.entry_fill_cutoff_et_minutes,
                    "max_notional": strategy.max_notional,
                    "long": {
                        "stop_loss_pct": strategy.long_stop_loss_pct,
                        "take_profit_pct": strategy.long_take_profit_pct,
                        "min_confirm_bars": strategy.long_min_confirm_bars,
                        "min_trend_gap": strategy.long_min_trend_gap,
                        "min_vwap_gap": strategy.long_min_vwap_gap,
                        "min_score": strategy.long_min_score,
                    },
                    "short": {
                        "stop_loss_pct": strategy.short_stop_loss_pct,
                        "take_profit_pct": strategy.short_take_profit_pct,
                        "min_confirm_bars": strategy.short_min_confirm_bars,
                        "min_trend_gap": strategy.short_min_trend_gap,
                        "min_vwap_gap": strategy.short_min_vwap_gap,
                        "min_score": strategy.short_min_score,
                    },
                }
            else:
                strategy_report = {
                    "benchmark_symbol": strategy.benchmark_symbol,
                    "profile": args.profile,
                    "fast": getattr(strategy, "fast_window", None),
                    "slow": getattr(strategy, "slow_window", None),
                    "trend_window": getattr(strategy, "trend_window", None),
                    "trend_lookback": getattr(strategy, "trend_lookback", None),
                    "min_bars": getattr(strategy, "min_bars", None),
                    "stop_loss_pct": strategy.stop_loss_pct,
                    "take_profit_pct": strategy.take_profit_pct,
                    "min_confirm_bars": getattr(strategy, "min_confirm_bars", None),
                    "min_trend_gap": getattr(strategy, "min_trend_gap", None),
                    "min_vwap_gap": getattr(strategy, "min_vwap_gap", None),
                    "min_score": getattr(strategy, "min_score", None),
                    "require_benchmark_confirmation": getattr(
                        strategy, "require_benchmark_confirmation", None
                    ),
                    "require_vwap_confirmation": getattr(
                        strategy, "require_vwap_confirmation", None
                    ),
                    "max_notional": getattr(strategy, "max_notional", None),
                }
            report: dict[str, object] = {
                "strategy": strategy_report,
                "cost_model": {
                    "commission_per_order": cost_model.commission_per_order,
                    "slippage_bps": cost_model.slippage_bps,
                    "spread_bps": cost_model.spread_bps,
                },
                "execution_model": {
                    "entry": "next_bar_open",
                    "protective_oca": "intrabar_after_entry_bar",
                    "ambiguous_stop_take_bar": "protective_stop_first",
                    "software_exit": "completed_bar_then_next_bar_open",
                },
                "validation": {
                    "method": "fixed-parameter chronological walk-forward",
                    "selection_performed": False,
                    "overlapping_lookbacks_treated_as_independent": False,
                    "duration": args.duration,
                    "train_days": args.train_days,
                    "test_days": args.test_days,
                    "step_days": args.step_days,
                    "holdout_days": args.holdout_days,
                    "data_source": "daily cache" if args.reuse_data else "IBKR",
                    "market_data_exchange": args.market_data_exchange,
                    "data_dir": str(Path(args.data_dir).resolve()),
                },
            }
            bars_by_symbol: dict[str, list[Bar]] = {}
            if args.reuse_data:
                try:
                    require_market_data_source(
                        args.data_dir, args.market_data_exchange
                    )
                except ValueError as exc:
                    raise BrokerError(
                        "historical data source preflight failed: " + str(exc)
                    ) from exc
            for symbol in strategy.symbols:
                if args.reuse_data:
                    bars_by_symbol[symbol] = load_bars(
                        args.data_dir, symbol, "5 mins", duration=args.duration
                    )
                else:
                    bars_by_symbol[symbol] = broker.historical_bars_paged(
                        symbol,
                        duration=args.duration,
                        bar_size="5 mins",
                        page_callback=lambda rows, cached_symbol=symbol: save_bars_by_day(
                            args.data_dir,
                            cached_symbol,
                            "5 mins",
                            rows,
                            exchange=args.market_data_exchange,
                        ),
                        exchange=args.market_data_exchange,
                    )
            benchmark = strategy.benchmark_symbol
            if args.reuse_data:
                bars_by_symbol[benchmark] = load_bars(
                    args.data_dir, benchmark, "5 mins", duration=args.duration
                )
            else:
                bars_by_symbol[benchmark] = broker.historical_bars_paged(
                    benchmark,
                    duration=args.duration,
                    bar_size="5 mins",
                    page_callback=lambda rows: save_bars_by_day(
                        args.data_dir,
                        benchmark,
                        "5 mins",
                        rows,
                        exchange=args.market_data_exchange,
                    ),
                    exchange=args.market_data_exchange,
                )
            missing = [symbol for symbol, bars in bars_by_symbol.items() if not bars]
            if missing:
                raise BrokerError(
                    "no historical bars available for " + ", ".join(sorted(missing))
                )
            try:
                historical_preflight = validate_historical_bar_coverage(
                    bars_by_symbol, recent_sessions=2
                )
            except ValueError as exc:
                raise BrokerError(
                    f"historical data preflight failed; refresh the cache before backtesting: {exc}"
                ) from exc
            report["historical_preflight"] = historical_preflight
            evaluation = evaluate_fixed_strategy_walk_forward(
                bars_by_symbol,
                strategy,
                cost_model,
                args.capital,
                train_days=args.train_days,
                test_days=args.test_days,
                step_days=args.step_days,
                holdout_days=args.holdout_days,
            )
            if isinstance(strategy, SemiconductorRotationStrategy):
                stability_strategies = {
                    "lenient_0.8x": replace(
                        strategy,
                        long_min_score=strategy.long_min_score * 0.8,
                        short_min_score=strategy.short_min_score * 0.8,
                        long_min_trend_gap=strategy.long_min_trend_gap * 0.8,
                        short_min_trend_gap=strategy.short_min_trend_gap * 0.8,
                    ),
                    "base": strategy,
                    "strict_1.2x": replace(
                        strategy,
                        long_min_score=strategy.long_min_score * 1.2,
                        short_min_score=strategy.short_min_score * 1.2,
                        long_min_trend_gap=strategy.long_min_trend_gap * 1.2,
                        short_min_trend_gap=strategy.short_min_trend_gap * 1.2,
                    ),
                }
            else:
                stability_strategies = {
                    "lenient_0.8x": replace(
                        strategy,
                        min_score=strategy.min_score * 0.8,
                        min_trend_gap=strategy.min_trend_gap * 0.8,
                    ),
                    "base": strategy,
                    "strict_1.2x": replace(
                        strategy,
                        min_score=strategy.min_score * 1.2,
                        min_trend_gap=strategy.min_trend_gap * 1.2,
                    ),
                }
            stability = evaluate_parameter_stability(
                bars_by_symbol,
                stability_strategies,
                cost_model,
                args.capital,
                train_days=args.train_days,
                test_days=args.test_days,
                step_days=args.step_days,
                holdout_days=args.holdout_days,
            )

            def result_report(result):
                return {
                    "gross_return_pct": round(result.gross_return_pct, 2),
                    "net_return_pct": round(result.net_return_pct, 2),
                    "trade_count": result.trade_count,
                    "win_count": result.win_count,
                    "loss_count": result.loss_count,
                    "commission_paid": round(result.total_commission, 2),
                    "spread_cost": round(result.total_spread_cost, 2),
                    "slippage_cost": round(result.total_slippage_cost, 2),
                }

            report["walk_forward_folds"] = [
                {
                    "train_start": fold.train_start.isoformat(),
                    "train_end": fold.train_end.isoformat(),
                    "test_start": fold.test_start.isoformat(),
                    "test_end": fold.test_end.isoformat(),
                    **result_report(fold.result),
                }
                for fold in evaluation.folds
            ]
            report["final_holdout"] = {
                "start": evaluation.holdout_start.isoformat(),
                "end": evaluation.holdout_end.isoformat(),
                **result_report(evaluation.holdout),
            }
            report["parameter_stability"] = {
                "holdout_accessed": False,
                "multiple_testing_method": "Bonferroni across 3 pre-holdout variants",
                "p_value_note": "normal approximation over non-overlapping OOS fold returns; descriptive, not proof of edge",
                "variants": [
                    {
                        "name": item.name,
                        "fold_count": item.fold_count,
                        "mean_oos_return_pct": round(item.mean_oos_return_pct, 4),
                        "min_oos_return_pct": round(item.min_oos_return_pct, 4),
                        "max_oos_return_pct": round(item.max_oos_return_pct, 4),
                        "positive_fold_ratio": round(item.positive_fold_ratio, 4),
                        "approximate_two_sided_p_value": item.approximate_two_sided_p_value,
                        "bonferroni_p_value": item.bonferroni_p_value,
                    }
                    for item in stability
                ],
            }
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
    finally:
        if broker is not None:
            broker.disconnect()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
