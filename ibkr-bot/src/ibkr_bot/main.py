from __future__ import annotations

import argparse
import sys

from ibkr_bot.alerts import AlertSink
from ibkr_bot.backtest import (
    run_intraday_signal_backtest,
    run_intraday_walk_forward_backtest,
    run_quality_low_vol_rotation_backtest,
)
from ibkr_bot.broker import IbkrBroker
from ibkr_bot.config import Settings, load_settings
from ibkr_bot.models import ContractSpec, PositionSnapshot, QuoteSnapshot, RiskState
from ibkr_bot.risk import RiskManager
from ibkr_bot.storage import Store
from ibkr_bot.strategy import (
    DEFAULT_ETF_CATALOG,
    DEFAULT_TECH_SEMICONDUCTOR_CATALOG,
    FiveMinuteMomentumStrategy,
    MovingAverageCrossStrategy,
    OpeningRangeBreakoutStrategy,
    QualityLowVolRotationStrategy,
    RotationPlan,
    ShortTermMomentumRotationStrategy,
    TechSemiconductorRotationStrategy,
    VwapPullbackStrategy,
    WeeklyMomentumRotationStrategy,
    VolatilityManagedTrendStrategy,
)
from ibkr_bot.strategy.base import Bar

DEFAULT_INTRADAY_PULLBACK_CATALOG: tuple[str, ...] = ("SOXL", "TQQQ", "TECL")


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
        choices=[
            "volatility_managed_trend",
            "moving_average_cross",
            "quality_low_vol_rotation",
            "weekly_momentum_rotation",
            "tech_semiconductor_rotation",
            "five_minute_momentum",
            "opening_range_breakout",
            "vwap_pullback",
        ],
    )
    scan_parser.add_argument("--duration", default=None)
    scan_parser.add_argument("--bar-size", default=None)
    rebalance = subparsers.add_parser("rebalance")
    rebalance.add_argument("--symbol", action="append", default=None)
    rebalance.add_argument(
        "--strategy",
        default="quality_low_vol_rotation",
        choices=["quality_low_vol_rotation"],
    )
    backtest = subparsers.add_parser("backtest")
    backtest.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override the backtest universe; defaults to the automatic ETF catalog",
    )
    backtest.add_argument("--duration", default="5 Y")
    backtest.add_argument("--bar-size", default=None)
    backtest.add_argument("--capital", type=float, default=10_000.0)
    backtest.add_argument(
        "--strategy",
        default="quality_low_vol_rotation",
        choices=[
            "quality_low_vol_rotation",
            "short_term_momentum_rotation",
            "weekly_momentum_rotation",
            "tech_semiconductor_rotation",
            "five_minute_momentum",
            "opening_range_breakout",
            "vwap_pullback",
        ],
    )
    backtest.add_argument(
        "--profile",
        default=None,
        choices=["monthly", "daily", "low_turnover", "defensive"],
        help="preset backtest defaults; explicit window arguments still override the preset",
    )
    backtest.add_argument(
        "--rebalance-frequency",
        default=None,
        choices=["monthly", "weekly", "daily"],
        help="how often the rotation model re-evaluates its holdings during backtest",
    )
    backtest.add_argument("--lookback", type=int, default=None)
    backtest.add_argument("--volatility-window", type=int, default=None)
    backtest.add_argument("--volume-window", type=int, default=None)
    backtest.add_argument("--max-annualized-volatility", type=float, default=None)
    backtest.add_argument("--min-trailing-return", type=float, default=None)
    backtest.add_argument("--switch-score-margin", type=float, default=None)
    backtest.add_argument(
        "--validation-split",
        type=float,
        default=None,
        help="optional walk-forward split for intraday strategies; prints in-sample and out-of-sample summaries",
    )
    backtest.add_argument("--market-filter-symbol", default=None)
    backtest.add_argument("--market-filter-window", type=int, default=None)
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
        rotation_symbols = _resolve_rotation_symbols(settings, args.symbol, args.strategy)
        with IbkrBroker(settings) as broker:
            positions = broker.positions()
            if args.strategy == "quality_low_vol_rotation":
                plan = _build_rotation_plan(broker, store, rotation_symbols, positions)
                alerts.send(_format_rotation_scan(plan))
                return 0

            symbols = _resolve_scan_symbols(settings, args.symbol, args.strategy, rotation_symbols)
            scan_options = _resolve_scan_options(args)
            strategy = _build_scan_strategy(args.strategy)
            if args.strategy in {"five_minute_momentum", "opening_range_breakout", "vwap_pullback"}:
                candidates = []
                for symbol in symbols:
                    bars = _load_historical_bars(
                        broker,
                        symbol,
                        scan_options["duration"],
                        scan_options["bar_size"],
                        scan_options["use_rth"],
                    )
                    candidate = strategy.score(symbol, bars)
                    store.record_signal(
                        symbol,
                        strategy.name,
                        {
                            "bar_count": len(bars),
                            "last_close": bars[-1].close if bars else None,
                            "score": candidate.score if candidate else None,
                            "signal": candidate.signal if candidate else None,
                        },
                    )
                    if candidate is not None:
                        candidates.append(candidate)
                alerts.send(_format_intraday_scan(candidates))
                return 0

            messages: list[str] = []
            for symbol in symbols:
                bars = _load_historical_bars(
                    broker,
                    symbol,
                    scan_options["duration"],
                    scan_options["bar_size"],
                    scan_options["use_rth"],
                )
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

    if args.command == "rebalance":
        store.init_db()
        rotation_symbols = _resolve_rotation_symbols(settings, args.symbol, args.strategy)
        with IbkrBroker(settings) as broker:
            positions = broker.positions()
            plan = _build_rotation_plan(broker, store, rotation_symbols, positions)
            if not plan.orders:
                alerts.send(_format_rotation_scan(plan))
                return 0
            _execute_rotation_plan(settings, store, alerts, broker, plan)
        return 0

    if args.command == "backtest":
        symbols = _resolve_rotation_symbols(settings, args.symbol, args.strategy)
        backtest_options = _resolve_backtest_options(args)
        with IbkrBroker(settings) as broker:
            universe = {}
            for symbol in symbols:
                if args.strategy in {"five_minute_momentum", "opening_range_breakout", "vwap_pullback"}:
                    bars = _load_historical_bars(
                        broker,
                        symbol,
                        str(backtest_options["duration"]),
                        str(backtest_options["bar_size"]),
                        bool(backtest_options["use_rth"]),
                    )
                else:
                    bars = _load_historical_bars(broker, symbol, args.duration)
                if bars:
                    universe[symbol] = bars
        strategy = _build_backtest_strategy(args.strategy, backtest_options)
        if args.strategy in {"five_minute_momentum", "opening_range_breakout", "vwap_pullback"}:
            if args.validation_split is not None:
                validation = run_intraday_walk_forward_backtest(
                    universe=universe,
                    strategy=strategy,
                    starting_capital=args.capital,
                    validation_split=float(args.validation_split),
                )
                print("in_sample:")
                print(_format_backtest_summary(validation.in_sample))
                print("out_of_sample:")
                print(_format_backtest_summary(validation.out_of_sample))
                return 0
            summary, _curve = run_intraday_signal_backtest(
                universe=universe,
                strategy=strategy,
                starting_capital=args.capital,
            )
        else:
            summary, _curve = run_quality_low_vol_rotation_backtest(
                universe=universe,
                strategy=strategy,
                starting_capital=args.capital,
                rebalance_frequency=str(backtest_options["rebalance_frequency"]),
            )
        print(_format_backtest_summary(summary))
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


def _resolve_rotation_symbols(
    settings: Settings,
    overrides: list[str] | None,
    strategy_name: str | None = None,
) -> list[str]:
    if overrides:
        return [symbol.strip().upper() for symbol in overrides if symbol.strip()]
    if settings.rotation_symbols:
        return [symbol.upper() for symbol in settings.rotation_symbols]
    if strategy_name in {"opening_range_breakout", "vwap_pullback"}:
        return list(DEFAULT_INTRADAY_PULLBACK_CATALOG)
    if strategy_name == "tech_semiconductor_rotation":
        return list(DEFAULT_TECH_SEMICONDUCTOR_CATALOG)
    return list(DEFAULT_ETF_CATALOG)


def _resolve_scan_symbols(
    settings: Settings,
    overrides: list[str] | None,
    strategy_name: str,
    rotation_symbols: list[str],
) -> list[str]:
    if overrides:
        return [symbol.strip().upper() for symbol in overrides if symbol.strip()]
    if strategy_name in {
        "quality_low_vol_rotation",
        "weekly_momentum_rotation",
        "tech_semiconductor_rotation",
        "five_minute_momentum",
        "opening_range_breakout",
        "vwap_pullback",
    }:
        return rotation_symbols
    return _resolve_symbol_list(settings.symbols, overrides)


def _resolve_backtest_options(args: argparse.Namespace) -> dict[str, int | float | str | bool]:
    strategy_name = getattr(args, "strategy", "quality_low_vol_rotation")
    profile = getattr(args, "profile", None)

    if strategy_name == "five_minute_momentum":
        defaults: dict[str, int | float | str | bool] = {
            "rebalance_frequency": "daily",
            "duration": "2 D",
            "bar_size": "5 mins",
            "use_rth": True,
            "lookback": 3,
            "volatility_window": 8,
            "volume_window": 4,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif strategy_name == "opening_range_breakout":
        defaults = {
            "rebalance_frequency": "daily",
            "duration": "5 D",
            "bar_size": "5 mins",
            "use_rth": True,
            "lookback": 6,
            "volatility_window": 8,
            "volume_window": 4,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.01,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif strategy_name == "vwap_pullback":
        defaults = {
            "rebalance_frequency": "daily",
            "duration": "5 D",
            "bar_size": "5 mins",
            "use_rth": True,
            "lookback": 12,
            "trend_window": 16,
            "volatility_window": 8,
            "volume_window": 4,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "min_trend_return": 0.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif strategy_name == "weekly_momentum_rotation":
        defaults = {
            "rebalance_frequency": "weekly",
            "lookback": 20,
            "volatility_window": 10,
            "volume_window": 10,
            "max_annualized_volatility": 0.30,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.02,
            "market_filter_symbol": "SPY",
            "market_filter_window": 50,
        }
    elif strategy_name == "tech_semiconductor_rotation":
        defaults = {
            "rebalance_frequency": "weekly",
            "lookback": 60,
            "volatility_window": 20,
            "volume_window": 20,
            "max_annualized_volatility": 0.35,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.03,
            "market_filter_symbol": "SPY",
            "market_filter_window": 50,
        }
    elif profile == "daily":
        defaults: dict[str, int | float | str] = {
            "rebalance_frequency": "daily",
            "lookback": 10,
            "volatility_window": 5,
            "volume_window": 5,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif profile == "monthly":
        defaults = {
            "rebalance_frequency": "monthly",
            "lookback": 60,
            "volatility_window": 20,
            "volume_window": 20,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif profile == "low_turnover":
        defaults = {
            "rebalance_frequency": "weekly",
            "lookback": 60,
            "volatility_window": 20,
            "volume_window": 20,
            "max_annualized_volatility": 0.25,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.03,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    elif profile == "defensive":
        defaults = {
            "rebalance_frequency": "weekly",
            "lookback": 60,
            "volatility_window": 20,
            "volume_window": 20,
            "max_annualized_volatility": 0.25,
            "min_trailing_return": 0.0,
            "switch_score_margin": 0.05,
            "market_filter_symbol": "SPY",
            "market_filter_window": 200,
        }
    elif strategy_name == "short_term_momentum_rotation":
        defaults = {
            "rebalance_frequency": "daily",
            "lookback": 30,
            "volatility_window": 10,
            "volume_window": 20,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }
    else:
        defaults = {
            "rebalance_frequency": "monthly",
            "lookback": 60,
            "volatility_window": 20,
            "volume_window": 20,
            "max_annualized_volatility": 0.20,
            "min_trailing_return": -1.0,
            "switch_score_margin": 0.0,
            "market_filter_symbol": "SPY",
            "market_filter_window": 0,
        }

    options: dict[str, int | float | str | bool] = {
        "rebalance_frequency": args.rebalance_frequency or defaults["rebalance_frequency"],
        "lookback": args.lookback or defaults["lookback"],
        "trend_window": getattr(args, "trend_window", None)
        if getattr(args, "trend_window", None) is not None
        else defaults.get("trend_window", defaults["lookback"]),
        "volatility_window": args.volatility_window or defaults["volatility_window"],
        "volume_window": args.volume_window or defaults["volume_window"],
        "max_annualized_volatility": getattr(args, "max_annualized_volatility", None)
        if getattr(args, "max_annualized_volatility", None) is not None
        else defaults["max_annualized_volatility"],
        "min_trailing_return": getattr(args, "min_trailing_return", None)
        if getattr(args, "min_trailing_return", None) is not None
        else defaults["min_trailing_return"],
        "min_trend_return": getattr(args, "min_trend_return", None)
        if getattr(args, "min_trend_return", None) is not None
        else defaults.get("min_trend_return", 0.0),
        "switch_score_margin": getattr(args, "switch_score_margin", None)
        if getattr(args, "switch_score_margin", None) is not None
        else defaults["switch_score_margin"],
        "market_filter_symbol": getattr(args, "market_filter_symbol", None) or defaults["market_filter_symbol"],
        "market_filter_window": getattr(args, "market_filter_window", None)
        if getattr(args, "market_filter_window", None) is not None
        else defaults["market_filter_window"],
    }
    if strategy_name == "five_minute_momentum":
        options.update(
            {
                "duration": getattr(args, "duration", None) or defaults["duration"],
                "bar_size": getattr(args, "bar_size", None) or defaults["bar_size"],
                "use_rth": defaults["use_rth"],
            }
        )
    elif strategy_name in {"opening_range_breakout", "vwap_pullback"}:
        options.update(
            {
                "duration": getattr(args, "duration", None) or defaults["duration"],
                "bar_size": getattr(args, "bar_size", None) or defaults["bar_size"],
                "use_rth": defaults["use_rth"],
            }
        )
    return options


def _build_backtest_strategy(name: str, options: dict[str, int | float | str | bool]):
    if name == "quality_low_vol_rotation":
        return QualityLowVolRotationStrategy(
            lookback=int(options["lookback"]),
            volatility_window=int(options["volatility_window"]),
            volume_window=int(options["volume_window"]),
            max_annualized_volatility=float(options["max_annualized_volatility"]),
            min_trailing_return=float(options["min_trailing_return"]),
            switch_score_margin=float(options["switch_score_margin"]),
            market_filter_symbol=str(options["market_filter_symbol"]),
            market_filter_window=int(options["market_filter_window"]),
        )
    if name == "short_term_momentum_rotation":
        return ShortTermMomentumRotationStrategy(
            lookback=int(options["lookback"]),
            volatility_window=int(options["volatility_window"]),
            volume_window=int(options["volume_window"]),
        )
    if name == "weekly_momentum_rotation":
        return WeeklyMomentumRotationStrategy(
            lookback=int(options["lookback"]),
            volatility_window=int(options["volatility_window"]),
            volume_window=int(options["volume_window"]),
            max_annualized_volatility=float(options["max_annualized_volatility"]),
            min_trailing_return=float(options["min_trailing_return"]),
            switch_score_margin=float(options["switch_score_margin"]),
            market_filter_symbol=str(options["market_filter_symbol"]),
            market_filter_window=int(options["market_filter_window"]),
        )
    if name == "tech_semiconductor_rotation":
        return TechSemiconductorRotationStrategy(
            lookback=int(options["lookback"]),
            volatility_window=int(options["volatility_window"]),
            volume_window=int(options["volume_window"]),
            max_annualized_volatility=float(options["max_annualized_volatility"]),
            min_trailing_return=float(options["min_trailing_return"]),
            switch_score_margin=float(options["switch_score_margin"]),
            market_filter_symbol=str(options["market_filter_symbol"]),
            market_filter_window=int(options["market_filter_window"]),
        )
    if name == "five_minute_momentum":
        return FiveMinuteMomentumStrategy(
            fast_window=int(options["lookback"]),
            slow_window=int(options["volatility_window"]),
            volume_window=int(options["volume_window"]),
        )
    if name == "opening_range_breakout":
        return OpeningRangeBreakoutStrategy(
            opening_range_bars=int(options["lookback"]),
            volume_window=int(options["volume_window"]),
            switch_score_margin=float(options["switch_score_margin"]),
        )
    if name == "vwap_pullback":
        return VwapPullbackStrategy(
            pullback_window=int(options["lookback"]),
            trend_window=int(options["trend_window"]),
            volume_window=int(options["volume_window"]),
            pullback_depth=0.0075,
            min_volume_multiple=1.0,
            min_trend_return=float(options["min_trend_return"]),
            switch_score_margin=float(options["switch_score_margin"]),
            entry_requires_cross=True,
            stop_loss_pct=0.015,
            max_hold_bars=36,
        )
    raise ValueError(f"unknown backtest strategy: {name}")


def _build_strategy(name: str):
    if name == "moving_average_cross":
        return MovingAverageCrossStrategy()
    if name == "volatility_managed_trend":
        return VolatilityManagedTrendStrategy()
    raise ValueError(f"unknown strategy: {name}")


def _build_scan_strategy(name: str):
    if name in {"moving_average_cross", "volatility_managed_trend"}:
        return _build_strategy(name)
    if name == "quality_low_vol_rotation":
        return QualityLowVolRotationStrategy()
    if name == "weekly_momentum_rotation":
        return WeeklyMomentumRotationStrategy()
    if name == "tech_semiconductor_rotation":
        return TechSemiconductorRotationStrategy()
    if name == "opening_range_breakout":
        return OpeningRangeBreakoutStrategy()
    if name == "vwap_pullback":
        return VwapPullbackStrategy()
    if name == "five_minute_momentum":
        return FiveMinuteMomentumStrategy()
    raise ValueError(f"unknown scan strategy: {name}")


def _build_rotation_plan(
    broker: IbkrBroker,
    store: Store,
    symbols: list[str],
    positions: dict[str, PositionSnapshot],
) -> RotationPlan:
    strategy = QualityLowVolRotationStrategy()
    universe: dict[str, list[Bar]] = {}
    for symbol in symbols:
        bars = _load_historical_bars(broker, symbol, "30 D")
        if not bars:
            store.record_signal(symbol, strategy.name, {"status": "unavailable"})
            continue
        universe[symbol] = bars
        score = strategy.score(symbol, bars)
        payload = {
            "bar_count": len(bars),
            "last_close": bars[-1].close if bars else None,
            "score": score.score if score else None,
            "trailing_return": score.trailing_return if score else None,
            "annualized_volatility": score.annualized_volatility if score else None,
            "max_drawdown": score.max_drawdown if score else None,
            "consistency": score.consistency if score else None,
        }
        store.record_signal(symbol, strategy.name, payload)
    return strategy.build_plan(universe, positions)


def _load_historical_bars(
    broker: IbkrBroker,
    symbol: str,
    duration: str,
    bar_size: str = "1 day",
    use_rth: bool = True,
) -> list[Bar]:
    try:
        return broker.historical_bars(
            ContractSpec(symbol=symbol),
            duration=duration,
            bar_size=bar_size,
            use_rth=use_rth,
        )
    except Exception:
        return []


def _resolve_scan_options(args: argparse.Namespace) -> dict[str, str | bool]:
    if args.strategy in {"five_minute_momentum", "opening_range_breakout", "vwap_pullback"}:
        defaults = {"duration": "2 D", "bar_size": "5 mins", "use_rth": True}
    else:
        defaults = {"duration": "30 D", "bar_size": "1 day", "use_rth": True}

    return {
        "duration": args.duration or defaults["duration"],
        "bar_size": args.bar_size or defaults["bar_size"],
        "use_rth": defaults["use_rth"],
    }


def _execute_rotation_plan(
    settings: Settings,
    store: Store,
    alerts: AlertSink,
    broker: IbkrBroker,
    plan: RotationPlan,
) -> None:
    messages: list[str] = []
    for order in plan.orders:
        state = RiskState(
            positions=broker.positions(),
            orders_today=store.orders_today(),
            realized_pnl_today=0.0,
        )
        decision = RiskManager(settings).evaluate(order, state)
        broker_order_id = None
        if decision.accepted and not settings.dry_run:
            broker_order_id = broker.place_order(order)
        store.record_order_intent(order, decision, settings.dry_run, broker_order_id)
        messages.append(
            f"{order.contract.symbol}: {order.side.value} {order.quantity} "
            f"@{order.limit_price}; accepted={decision.accepted}; reasons={list(decision.reasons)}"
        )
    alerts.send("\n".join(messages) if messages else "IBKR bot: rotation produced no orders")


def _format_rotation_scan(plan: object) -> str:
    lines: list[str] = []
    selected = plan.selected_symbol
    for candidate in plan.candidates:
        marker = "*" if candidate.symbol == selected else " "
        lines.append(
            f"{marker} {candidate.symbol}: score={candidate.score:.4f} "
            f"ret={candidate.trailing_return:.3%} vol={candidate.annualized_volatility:.3%} "
            f"dd={candidate.max_drawdown:.3%} consistency={candidate.consistency:.3f} "
            f"avg_vol={candidate.average_volume:.0f}"
        )
    if not lines:
        return "IBKR bot: no rotation candidates"
    return "\n".join(lines)


def _format_intraday_scan(candidates: list[object]) -> str:
    if not candidates:
        return "IBKR bot: no intraday momentum candidates"

    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    lines: list[str] = []
    for candidate in ranked[:8]:
        parts = [f"{candidate.symbol}: signal={getattr(candidate, 'signal', 'NONE')} score={candidate.score:.6f}"]
        if hasattr(candidate, "momentum"):
            parts.append(f"momentum={getattr(candidate, 'momentum'):.3%}")
        if hasattr(candidate, "volume_multiple"):
            parts.append(f"vol_x={getattr(candidate, 'volume_multiple'):.2f}")
        if hasattr(candidate, "fast_sma") and hasattr(candidate, "slow_sma"):
            parts.append(f"fast={getattr(candidate, 'fast_sma'):.2f} slow={getattr(candidate, 'slow_sma'):.2f}")
        if hasattr(candidate, "opening_range_high") and hasattr(candidate, "opening_range_low"):
            parts.append(
                f"or_high={getattr(candidate, 'opening_range_high'):.2f} "
                f"or_low={getattr(candidate, 'opening_range_low'):.2f}"
            )
        if hasattr(candidate, "vwap"):
            parts.append(f"vwap={getattr(candidate, 'vwap'):.2f}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _format_backtest_summary(summary) -> str:
    selected = ", ".join(
        f"{symbol}:{count}" for symbol, count in sorted(summary.selected_symbol_counts.items())
    ) or "(none)"
    return "\n".join(
        [
            f"strategy: {summary.strategy}",
            f"rebalance_frequency: {summary.rebalance_frequency}",
            f"symbols: {', '.join(summary.symbols)}",
            f"range: {summary.start_date} -> {summary.end_date}",
            f"starting_capital: {summary.starting_capital:.2f}",
            f"ending_capital: {summary.ending_capital:.2f}",
            f"total_return: {summary.total_return:.2%}",
            f"cagr: {summary.cagr:.2%}",
            f"annualized_volatility: {summary.annualized_volatility:.2%}",
            f"max_drawdown: {summary.max_drawdown:.2%}",
            f"rebalance_count: {summary.rebalance_count}",
            f"trade_count: {summary.trade_count}",
            f"selected_symbols: {selected}",
        ]
    )


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
