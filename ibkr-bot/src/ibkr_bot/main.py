from __future__ import annotations

import argparse
import sys

from ibkr_bot.alerts import AlertSink
from ibkr_bot.broker import IbkrBroker
from ibkr_bot.config import load_settings
from ibkr_bot.models import ContractSpec, RiskState
from ibkr_bot.risk import RiskManager
from ibkr_bot.storage import Store
from ibkr_bot.strategy import MovingAverageCrossStrategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibkr-bot")
    parser.add_argument("--env-file", default=".env")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("check-connection")
    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--symbol", default=None)

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

    if args.command == "run-once":
        store.init_db()
        symbol = (args.symbol or settings.symbols[0]).upper()
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
                return 0

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
            return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

