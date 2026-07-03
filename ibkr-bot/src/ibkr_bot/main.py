from __future__ import annotations

import argparse
import sys

from ibkr_bot.alerts import AlertSink
from ibkr_bot.broker import IbkrBroker
from ibkr_bot.config import Settings, load_settings
from ibkr_bot.models import ContractSpec, QuoteSnapshot, RiskState
from ibkr_bot.risk import RiskManager
from ibkr_bot.storage import Store
from ibkr_bot.strategy import MovingAverageCrossStrategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibkr-bot")
    parser.add_argument("--env-file", default=".env")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("check-connection")
    quote_parser = subparsers.add_parser("quote")
    quote_parser.add_argument("--symbol", default=None)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--symbol", action="append", default=None)
    trade_once = subparsers.add_parser("trade-once")
    trade_once.add_argument("--symbol", default=None)
    subparsers.add_parser("run-once")

    args = parser.parse_args(argv)
    settings = load_settings(args.env_file)
    store = Store(settings.database_path)
    alerts = AlertSink(settings.alert_command)

    if args.command == "init-db":
        store.init_db()
        print(f"initialized database at {settings.database_path}")
        return 0

    if args.command == "check-connection":
        with IbkrBroker(settings) as broker:
            summary_count = len(broker.account_summary())
            print(f"connected to IBKR server_time={broker.server_time()} account_rows={summary_count}")
        return 0

    if args.command == "quote":
        symbol = _resolve_symbol(settings.symbols, args.symbol)
        with IbkrBroker(settings) as broker:
            snapshot = broker.quote(ContractSpec(symbol=symbol))
        alerts.send(_format_quote(snapshot))
        return 0

    if args.command == "scan":
        store.init_db()
        symbols = _resolve_symbol_list(settings.symbols, args.symbol)
        strategy = MovingAverageCrossStrategy()
        with IbkrBroker(settings) as broker:
            messages: list[str] = []
            for symbol in symbols:
                bars = broker.historical_bars(ContractSpec(symbol=symbol))
                store.record_signal(
                    symbol,
                    strategy.name,
                    {"bar_count": len(bars), "last_close": bars[-1].close if bars else None},
                )
                intent = strategy.generate(symbol, bars)
                if intent is None:
                    messages.append(f"{symbol}: no signal bars={len(bars)}")
                    continue
                messages.append(
                    f"{symbol}: {intent.side.value} {intent.quantity} "
                    f"{intent.order_type.value} @{intent.limit_price} "
                    f"bars={len(bars)} reason={intent.reason}"
                )
        alerts.send("\n".join(messages) if messages else "IBKR bot: scan returned no symbols")
        return 0

    if args.command in {"trade-once", "run-once"}:
        store.init_db()
        symbol = _resolve_symbol(settings.symbols, getattr(args, "symbol", None))
        _trade_once(settings, store, alerts, symbol)
        return 0

    return 2


def _resolve_symbol(defaults: tuple[str, ...], override: str | None) -> str:
    if override:
        return override.strip().upper()
    if not defaults:
        raise ValueError("IBKR_SYMBOLS must contain at least one symbol")
    return defaults[0].upper()


def _resolve_symbol_list(defaults: tuple[str, ...], overrides: list[str] | None) -> list[str]:
    if overrides:
        return [symbol.strip().upper() for symbol in overrides if symbol.strip()]
    if not defaults:
        raise ValueError("IBKR_SYMBOLS must contain at least one symbol")
    return [symbol.upper() for symbol in defaults]


def _trade_once(settings: Settings, store: Store, alerts: AlertSink, symbol: str) -> None:
    strategy = MovingAverageCrossStrategy()
    risk = RiskManager(settings)

    with IbkrBroker(settings) as broker:
        bars = broker.historical_bars(ContractSpec(symbol=symbol))
        store.record_signal(
            symbol,
            strategy.name,
            {"bar_count": len(bars), "last_close": bars[-1].close if bars else None},
        )
        intent = strategy.generate(symbol, bars)
        if intent is None:
            alerts.send(f"IBKR bot: no signal for {symbol}")
            return

        state = RiskState(
            positions=broker.positions(),
            orders_today=store.orders_today(),
            realized_pnl_today=0.0,
        )
        decision = risk.evaluate(intent, state)
        broker_order_id = None
        if decision.accepted and not settings.dry_run:
            broker_order_id = broker.place_order(intent)

        store.record_order_intent(intent, decision, settings.dry_run, broker_order_id)
        status = "accepted" if decision.accepted else "rejected"
        mode = "dry-run" if settings.dry_run else "submitted"
        alerts.send(
            f"IBKR bot: {status} {mode} {intent.side.value} {intent.quantity} "
            f"{symbol} {intent.order_type.value} @{intent.limit_price}; "
            f"reasons={list(decision.reasons)}"
        )
        return


def _format_quote(snapshot: QuoteSnapshot) -> str:
    fields = [
        f"{snapshot.symbol}: quote source={snapshot.source}",
        _format_metric("bid", snapshot.bid),
        _format_metric("ask", snapshot.ask),
        _format_metric("last", snapshot.last),
        _format_metric("close", snapshot.close),
        _format_metric("market", snapshot.market_price),
        _format_volume(snapshot.volume),
    ]
    if snapshot.timestamp:
        fields.append(f"time={snapshot.timestamp}")
    return " ".join(field for field in fields if field)


def _format_metric(name: str, value: float | None) -> str:
    if value is None:
        return f"{name}=n/a"
    return f"{name}={value:.2f}"


def _format_volume(value: int | None) -> str:
    if value is None:
        return "volume=n/a"
    return f"volume={value}"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
