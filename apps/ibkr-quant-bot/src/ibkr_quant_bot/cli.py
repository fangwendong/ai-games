from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .broker import IbkrBroker, format_table
from .config import Settings, load_settings
from .models import TradeRequest
from .risk import RiskManager
from .strategy import MovingAverageStrategy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ibkr-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="show local configuration and dependency status")

    quote = subparsers.add_parser("quote", help="fetch a market data snapshot")
    quote.add_argument("symbol")

    subparsers.add_parser("account", help="show account summary")
    subparsers.add_parser("balance", help="show cash, net liquidation, buying power, margin, and PnL")
    subparsers.add_parser("positions", help="show open positions")

    order = subparsers.add_parser("order", help="validate and optionally submit an order")
    order.add_argument("symbol")
    order.add_argument("action", choices=["BUY", "SELL"])
    order.add_argument("quantity", type=int)
    order.add_argument("--type", choices=["MKT", "LMT"], default="MKT")
    order.add_argument("--limit-price", type=float)
    order.add_argument("--reference-price", type=float, help="price used for dry-run notional checks")

    run_once = subparsers.add_parser("run-once", help="run the sample moving-average strategy once")
    run_once.add_argument("symbol")
    run_once.add_argument("--fast", type=int, default=5)
    run_once.add_argument("--slow", type=int, default=20)
    run_once.add_argument("--quantity", type=int, default=1)

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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()

    if args.command == "doctor":
        return _doctor(settings)

    broker = _with_broker(settings)
    try:
        if args.command == "quote":
            print(json.dumps(asdict(broker.quote(args.symbol)), indent=2, sort_keys=True))
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
            print(format_table(rows, ["account", "symbol", "secType", "exchange", "currency", "position", "avgCost"]))
            return 0

        if args.command == "order":
            request = TradeRequest(
                symbol=args.symbol.upper(),
                action=args.action.upper(),
                quantity=args.quantity,
                order_type=args.type,
                limit_price=args.limit_price,
            )
            reference_price = args.reference_price
            if reference_price is None:
                reference_price = request.limit_price or broker.quote(request.symbol).reference_price
            decision = RiskManager(settings).validate(request, reference_price)
            print(decision.reason)
            if decision.allowed:
                trade = broker.place_order(request)
                print(trade)
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
            risk_decision = RiskManager(settings).validate(request, decision.reference_price)
            print(risk_decision.reason)
            if risk_decision.allowed:
                trade = broker.place_order(request)
                print(trade)
            return 0
    finally:
        broker.disconnect()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
