from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .broker import BrokerError, IbkrBroker, format_table
from .backtest import BacktestCostModel, run_intraday_momentum_backtest
from .config import Settings, load_settings
from .models import Bar, TradeRequest
from .risk import RiskManager
from .strategy import IntradayMomentumStrategy, MovingAverageStrategy, SemiconductorRotationStrategy, VwapPullbackStrategy

NEW_YORK = ZoneInfo("America/New_York")


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

    vwap = subparsers.add_parser("vwap-pullback", help="scan SOXL/TQQQ/TECL and optionally auto-place limit orders")
    vwap.add_argument("--max-notional", type=float, default=None, help="cap per order notional")

    momentum = subparsers.add_parser(
        "intraday-momentum",
        help="scan SOXL/TQQQ/TECL with an intraday momentum rotation rule and manage exits",
    )
    momentum.add_argument("--max-notional", type=float, default=None, help="cap per order notional")
    momentum.add_argument(
        "--profile",
        choices=["balanced", "high-frequency", "rotation"],
        default="balanced",
        help="strategy preset; high-frequency increases trade count but usually weakens returns",
    )
    momentum.add_argument("--benchmark-symbol", type=str, default="QQQ", help="market regime benchmark symbol")
    momentum.add_argument("--fast", type=int, default=13, help="fast EMA window")
    momentum.add_argument("--slow", type=int, default=21, help="slow EMA window")
    momentum.add_argument("--trend-window", type=int, default=34, help="medium-term EMA regime window")
    momentum.add_argument("--trend-lookback", type=int, default=5, help="bars used for trend slope check")
    momentum.add_argument("--min-bars", type=int, default=30, help="minimum bars required before trading")
    momentum.add_argument("--stop-loss-pct", type=float, default=0.008, help="stop loss percentage")
    momentum.add_argument("--take-profit-pct", type=float, default=0.02, help="take profit percentage")
    momentum.add_argument("--min-confirm-bars", type=int, default=2, help="minimum consecutive bars above VWAP")
    momentum.add_argument("--min-trend-gap", type=float, default=0.0015, help="minimum fast/slow EMA gap")
    momentum.add_argument("--min-vwap-gap", type=float, default=0.0005, help="minimum close/vwap gap")
    momentum.add_argument("--min-score", type=float, default=0.008, help="minimum momentum score required")
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
    backtest.add_argument("--duration", nargs="+", default=["7 D", "14 D", "30 D"], help="historical windows to test")
    backtest.add_argument("--max-notional", type=float, default=None, help="cap per order notional")
    backtest.add_argument("--capital", type=float, default=1_000.0, help="starting capital")
    backtest.add_argument(
        "--profile",
        choices=["balanced", "high-frequency", "rotation"],
        default="balanced",
        help="strategy preset; high-frequency increases trade count but usually weakens returns",
    )
    backtest.add_argument("--benchmark-symbol", type=str, default="QQQ", help="market regime benchmark symbol")
    backtest.add_argument("--fast", type=int, default=13, help="fast EMA window")
    backtest.add_argument("--slow", type=int, default=21, help="slow EMA window")
    backtest.add_argument("--trend-window", type=int, default=34, help="medium-term EMA regime window")
    backtest.add_argument("--trend-lookback", type=int, default=5, help="bars used for trend slope check")
    backtest.add_argument("--min-bars", type=int, default=30, help="minimum bars required before trading")
    backtest.add_argument("--stop-loss-pct", type=float, default=0.008, help="stop loss percentage")
    backtest.add_argument("--take-profit-pct", type=float, default=0.02, help="take profit percentage")
    backtest.add_argument("--min-confirm-bars", type=int, default=2, help="minimum consecutive bars above VWAP")
    backtest.add_argument("--min-trend-gap", type=float, default=0.0015, help="minimum fast/slow EMA gap")
    backtest.add_argument("--min-vwap-gap", type=float, default=0.0005, help="minimum close/vwap gap")
    backtest.add_argument("--min-score", type=float, default=0.008, help="minimum momentum score required")
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
    backtest.add_argument("--commission-per-order", type=float, default=0.35, help="commission per order")
    backtest.add_argument("--slippage-bps", type=float, default=1.0, help="slippage in basis points per side")
    backtest.add_argument("--spread-bps", type=float, default=1.0, help="spread in basis points per side")

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


def _submit_or_print(broker: IbkrBroker, settings: Settings, request: TradeRequest, reason: str) -> None:
    print(reason)
    if settings.readonly or settings.dry_run:
        print("dry-run: order not submitted")
        return
    trade = broker.place_order(request)
    print(trade)


def _is_market_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(NEW_YORK)
    current = now.timetz().replace(tzinfo=None)
    return time(9, 30) <= current <= time(16, 0)


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
) -> list[Bar]:
    bars = broker.historical_bars(symbol, duration=duration, bar_size=bar_size, what_to_show=what_to_show)
    if not settings.is_live:
        return bars
    if not bars:
        raise BrokerError(f"no live bars returned for {symbol}")

    last_bar_time = _normalize_bar_time(bars[-1].time)
    now = datetime.now(NEW_YORK)
    age_seconds = (now - last_bar_time).total_seconds()
    max_age_seconds = max(settings.live_bar_max_age_seconds, _bar_size_seconds(bar_size) + 120)
    if age_seconds < -60:
        raise BrokerError(f"latest bar for {symbol} is in the future: {last_bar_time.isoformat()}")
    if age_seconds > max_age_seconds:
        age_minutes = age_seconds / 60
        max_minutes = max_age_seconds / 60
        raise BrokerError(
            f"latest bar for {symbol} is stale: {last_bar_time.isoformat()} "
            f"({age_minutes:.1f} min old; max {max_minutes:.1f}); refusing delayed data"
        )
    return bars


def _strategy_quote(broker: IbkrBroker, settings: Settings, symbol: str):
    if settings.is_live:
        return broker.live_quote(symbol)
    return broker.quote(symbol)


def _parse_position_rows(rows: list[dict[str, str]], symbols: tuple[str, ...]) -> dict[str, dict[str, str]]:
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
    if profile == "rotation":
        return SemiconductorRotationStrategy(
            benchmark_symbol=args.benchmark_symbol,
            max_notional=args.max_notional or settings.max_order_notional,
        )
    return IntradayMomentumStrategy(
        symbols=settings.vwap_symbols,
        benchmark_symbol=args.benchmark_symbol,
        max_notional=args.max_notional or settings.max_order_notional,
        **_momentum_kwargs(args),
        require_benchmark_confirmation=not args.no_benchmark_confirmation,
        require_vwap_confirmation=not args.no_vwap_confirmation,
    )


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
            risk_decision = RiskManager(settings).validate(request, decision.reference_price)
            print(risk_decision.reason)
            if risk_decision.allowed:
                _submit_or_print(broker, settings, request, risk_decision.reason)
            return 0

        if args.command == "vwap-pullback":
            if not _is_market_hours():
                print("market closed: skipping vwap_pullback scan")
                return 0

            strategy = VwapPullbackStrategy(
                symbols=settings.vwap_symbols,
                max_notional=args.max_notional or settings.max_order_notional,
            )
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
                        "limit_price": None if decision.limit_price is None else round(decision.limit_price, 2),
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
            symbol, decision = max(signal_decisions, key=lambda item: float(item[1].meta.get("close", 0.0)) - float(item[1].meta.get("vwap", 0.0)))
            request = TradeRequest(
                symbol=symbol,
                action="BUY",
                quantity=decision.quantity,
                order_type="LMT",
                limit_price=decision.limit_price,
            )
            risk_settings = replace(settings, allowed_symbols=strategy.symbols, max_order_notional=strategy.max_notional)
            risk_decision = RiskManager(risk_settings).validate(request, decision.reference_price)
            print(risk_decision.reason)
            if risk_decision.allowed:
                _submit_or_print(broker, settings, request, f"auto order candidate: {symbol} qty={decision.quantity} limit={decision.limit_price:.2f}")
            return 0

        if args.command == "intraday-momentum":
            if not _is_market_hours():
                print("market closed: skipping intraday_momentum scan")
                return 0

            strategy = _build_momentum_strategy(args, settings)
            benchmark_bars = _fresh_historical_bars(
                broker,
                settings,
                strategy.benchmark_symbol,
                bar_size="5 mins",
            )

            current_positions = _parse_position_rows(broker.positions(), strategy.symbols)
            scan_rows: list[dict[str, object]] = []
            decisions: dict[str, object] = {}

            for symbol in strategy.symbols:
                quote = _strategy_quote(broker, settings, symbol)
                bars = _fresh_historical_bars(broker, settings, symbol, bar_size="5 mins")
                if symbol in current_positions:
                    position_row = current_positions[symbol]
                    decision = strategy.exit_decide(
                        symbol,
                        quote,
                        bars,
                        int(float(position_row["position"])),
                        float(position_row["avgCost"]),
                    )
                else:
                    decision = strategy.decide(symbol, quote, bars, benchmark_bars=benchmark_bars)

                decisions[symbol] = decision
                scan_rows.append(
                    {
                        "symbol": symbol,
                        "action": decision.action,
                        "quantity": decision.quantity,
                        "reference_price": round(decision.reference_price, 2),
                        "limit_price": None if decision.limit_price is None else round(decision.limit_price, 2),
                        "signal": decision.signal,
                        "score": round(float(decision.meta.get("score", 0.0)), 6),
                        "reason": decision.reason,
                    }
                )

            print(json.dumps(scan_rows, indent=2, sort_keys=True))

            exit_candidates = [
                decision
                for symbol, decision in decisions.items()
                if symbol in current_positions and getattr(decision, "signal", False) and decision.action == "SELL"
            ]
            if exit_candidates:
                decision = exit_candidates[0]
                request = TradeRequest(
                    symbol=decision.symbol,
                    action="SELL",
                    quantity=int(float(current_positions[decision.symbol]["position"])),
                )
                risk_decision = RiskManager(settings).validate(request, decision.reference_price)
                print(risk_decision.reason)
                if risk_decision.allowed:
                    _submit_or_print(broker, settings, request, f"exit candidate: {decision.symbol} qty={request.quantity}")
                return 0

            if current_positions:
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

            decision = max(buy_candidates, key=lambda item: float(item.meta.get("score", 0.0)))
            request = TradeRequest(
                symbol=decision.symbol,
                action="BUY",
                quantity=decision.quantity,
                order_type="LMT",
                limit_price=decision.limit_price,
            )
            risk_settings = replace(settings, allowed_symbols=strategy.symbols, max_order_notional=strategy.max_notional)
            risk_decision = RiskManager(risk_settings).validate(request, decision.reference_price)
            print(risk_decision.reason)
            if risk_decision.allowed:
                _submit_or_print(broker, settings, request, f"auto order candidate: {decision.symbol} qty={decision.quantity} limit={decision.limit_price:.2f}")
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
                    "require_benchmark_confirmation": getattr(strategy, "require_benchmark_confirmation", None),
                    "require_vwap_confirmation": getattr(strategy, "require_vwap_confirmation", None),
                    "max_notional": getattr(strategy, "max_notional", None),
                }
            report: dict[str, object] = {
                "strategy": strategy_report,
                "cost_model": {
                    "commission_per_order": cost_model.commission_per_order,
                    "slippage_bps": cost_model.slippage_bps,
                    "spread_bps": cost_model.spread_bps,
                },
                "windows": {},
            }
            for duration in args.duration:
                bars_by_symbol: dict[str, list[Bar]] = {}
                for symbol in strategy.symbols:
                    bars_by_symbol[symbol] = broker.historical_bars(symbol, duration=duration, bar_size="5 mins")
                bars_by_symbol[strategy.benchmark_symbol] = broker.historical_bars(
                    strategy.benchmark_symbol,
                    duration=duration,
                    bar_size="5 mins",
                )
                result = run_intraday_momentum_backtest(
                    bars_by_symbol=bars_by_symbol,
                    strategy=strategy,
                    cost_model=cost_model,
                    initial_capital=args.capital,
                )
                report["windows"][duration] = {
                    "gross_return_pct": round(result.gross_return_pct, 2),
                    "net_return_pct": round(result.net_return_pct, 2),
                    "trade_count": result.trade_count,
                    "win_count": result.win_count,
                    "loss_count": result.loss_count,
                    "commission_paid": round(result.total_commission, 2),
                    "spread_cost": round(result.total_spread_cost, 2),
                    "slippage_cost": round(result.total_slippage_cost, 2),
                }
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
    finally:
        broker.disconnect()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
