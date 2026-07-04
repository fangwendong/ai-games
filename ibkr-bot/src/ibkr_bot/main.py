from __future__ import annotations

import argparse
import sys

from ibkr_bot.alerts import AlertSink
from ibkr_bot.broker import IbkrBroker
from ibkr_bot.config import Settings, load_settings
from ibkr_bot.models import ContractSpec, QuoteSnapshot, RiskState
from ibkr_bot.risk import RiskManager
from ibkr_bot.storage import Store
from ibkr_bot.strategy import MovingAverageCrossStrategy, VolatilityManagedTrendStrategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibkr-bot")
    parser.add_argument("--env-file", default=".env")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("check-connection")
    subparsers.add_parser("account")
    subparsers.add_parser("balance")
    subparsers.add_parser("positions")
    quote_parser = subparsers.add_parser("quote")
    quote_parser.add_argument("--symbol", default=None)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--symbol", action="append", default=None)
    scan_parser.add_argument(
        "--strategy",
        default="volatility_managed_trend",
        choices=["volatility_managed_trend", "moving_average_cross"],
    )
    trade_once = subparsers.add_parser("trade-once")
    trade_once.add_argument("--symbol", default=None)
    trade_once.add_argument(
        "--strategy",
        default="volatility_managed_trend",
        choices=["volatility_managed_trend", "moving_average_cross"],
    )
    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--symbol", default=None)
    run_once.add_argument(
        "--strategy",
        default="volatility_managed_trend",
        choices=["volatility_managed_trend", "moving_average_cross"],
    )

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

    if args.command == "account":
        with IbkrBroker(settings) as broker:
            rows = broker.account_summary()
        print(_format_rows(rows, ["account", "tag", "value", "currency"]))
        return 0

    if args.command == "balance":
        with IbkrBroker(settings) as broker:
            rows = broker.balance()
        print(_format_rows(rows, ["account", "tag", "value", "currency"]))
        return 0

    if args.command == "positions":
        with IbkrBroker(settings) as broker:
            rows = list(broker.positions().values())
        print(_format_rows(rows, ["symbol", "quantity", "market_price", "notional"]))
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
        strategy = _build_strategy(args.strategy)
        with IbkrBroker(settings) as broker:
            positions = broker.positions()
            messages: list[str] = []
            for symbol in symbols:
                bars = broker.historical_bars(ContractSpec(symbol=symbol))
                store.record_signal(
                    symbol,
                    strategy.name,
                    {"bar_count": len(bars), "last_close": bars[-1].close if bars else None},
                )
                intent = strategy.generate(symbol, bars, positions.get(symbol))
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
        strategy_name = getattr(args, "strategy", "volatility_managed_trend")
        _trade_once(settings, store, alerts, symbol, strategy_name)
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


def _build_strategy(name: str):
    if name == "moving_average_cross":
        return MovingAverageCrossStrategy()
    if name == "volatility_managed_trend":
        return VolatilityManagedTrendStrategy()
    raise ValueError(f"unknown strategy: {name}")


def _trade_once(settings: Settings, store: Store, alerts: AlertSink, symbol: str, strategy_name: str) -> None:
    strategy = _build_strategy(strategy_name)
    risk = RiskManager(settings)

    with IbkrBroker(settings) as broker:
        positions = broker.positions()
        bars = broker.historical_bars(ContractSpec(symbol=symbol))
        store.record_signal(
            symbol,
            strategy.name,
            {"bar_count": len(bars), "last_close": bars[-1].close if bars else None},
        )
        intent = strategy.generate(symbol, bars, positions.get(symbol))
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


def _format_rows(rows: list[object], columns: list[str]) -> str:
    dict_rows: list[dict[str, str]] = []
    for row in rows:
        dict_row: dict[str, str] = {}
        for column in columns:
            dict_row[column] = str(getattr(row, column, ""))
        dict_rows.append(dict_row)

    if not dict_rows:
        return "(no rows)"

    widths = {
        column: max(len(column), *(len(row[column]) for row in dict_rows))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    divider = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(row[column].ljust(widths[column]) for column in columns)
        for row in dict_rows
    ]
    return "\n".join([header, divider, *body])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
