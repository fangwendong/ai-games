from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .backtest import BacktestCostModel, BacktestTrade, run_intraday_momentum_backtest
from .cli import ROTATION_HYSTERESIS_V2_PARAMETERS
from .gap_reversion_research import (
    GapReversionConfig,
    GapReversionTrade,
    load_gap_reversion_config,
    run_gap_reversion_backtest,
)
from .historical_cache import load_bars
from .strategy import SemiconductorRotationStrategy


NEW_YORK = ZoneInfo("America/New_York")
STRATEGY_NAME = "GapGuard Fusion v1"
STRATEGY_VERSION = "gapguard-fusion-v1-research"


def _time_key(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class HybridTrade:
    session_date: date
    source: str
    symbol: str
    shares: int
    net_pnl: float


@dataclass(frozen=True)
class HybridResult:
    strategy_name: str
    strategy_version: str
    initial_capital: float
    ending_capital: float
    net_return_pct: float
    max_drawdown: float
    trade_count: int
    gap_trade_count: int
    trades: tuple[HybridTrade, ...]


def replay_earliest_signal(
    v2_trades: tuple[BacktestTrade, ...],
    gap_trades: tuple[GapReversionTrade, ...],
    gap_config: GapReversionConfig,
    cost: BacktestCostModel,
) -> HybridResult:
    """Replay one shared balance using only information known at entry time.

    The first actual fill wins the session. Frozen v2 wins an exact-time tie.
    """

    v2_by_day = {trade.entry_date: trade for trade in v2_trades}
    gap_by_day = {trade.session_date: trade for trade in gap_trades}
    capital = gap_config.initial_capital
    peak = capital
    max_drawdown = 0.0
    trades: list[HybridTrade] = []

    for session in sorted(set(v2_by_day) | set(gap_by_day)):
        v2_trade = v2_by_day.get(session)
        gap_trade = gap_by_day.get(session)
        if v2_trade is not None and v2_trade.entry_time is None:
            raise ValueError("v2 entry_time is required for causal hybrid replay")
        use_v2 = v2_trade is not None and (
            gap_trade is None
            or _time_key(v2_trade.entry_time) <= _time_key(gap_trade.entry_time)
        )
        if use_v2:
            trade = v2_trade
            raw_entry = trade.gross_entry_price
            raw_exit = trade.gross_exit_price
            shares = min(
                trade.shares,
                int(
                    max(0.0, capital - gap_config.commission_per_order)
                    // cost.buy_fill(raw_entry)
                ),
            )
            source = "rotation-hysteresis-v2"
            symbol = trade.symbol
        else:
            if gap_trade is None:
                continue
            trade = gap_trade
            raw_entry = trade.raw_entry_price
            raw_exit = trade.raw_exit_price
            shares = min(
                int(gap_config.max_risk_per_trade // trade.stop_distance),
                int(gap_config.max_notional // raw_entry),
                int(
                    max(0.0, capital - gap_config.commission_per_order)
                    // cost.buy_fill(raw_entry)
                ),
            )
            source = gap_config.strategy_version
            symbol = trade.symbol
        if shares <= 0:
            continue
        net_pnl = (
            shares * (cost.sell_fill(raw_exit) - cost.buy_fill(raw_entry))
            - cost.commission(shares, side="BUY")
            - cost.commission(shares, side="SELL")
        )
        capital += net_pnl
        peak = max(peak, capital)
        max_drawdown = max(max_drawdown, peak - capital)
        trades.append(
            HybridTrade(
                session_date=session,
                source=source,
                symbol=symbol,
                shares=shares,
                net_pnl=net_pnl,
            )
        )

    gap_count = sum(
        trade.source == gap_config.strategy_version for trade in trades
    )
    return HybridResult(
        strategy_name=STRATEGY_NAME,
        strategy_version=STRATEGY_VERSION,
        initial_capital=gap_config.initial_capital,
        ending_capital=capital,
        net_return_pct=(capital / gap_config.initial_capital - 1.0) * 100.0,
        max_drawdown=max_drawdown,
        trade_count=len(trades),
        gap_trade_count=gap_count,
        trades=tuple(trades),
    )


def _date_of_bar(bar: object) -> date:
    value = getattr(bar, "time")
    return value.date() if value.tzinfo is None else value.astimezone(NEW_YORK).date()


def evaluate_period(
    v2_bars: dict[str, list],
    gap_bars: dict[str, list],
    gap_config: GapReversionConfig,
    start: date,
    end: date,
) -> tuple[float, HybridResult]:
    cost = BacktestCostModel(
        gap_config.commission_per_order,
        gap_config.slippage_bps,
        gap_config.spread_bps,
    )
    strategy = SemiconductorRotationStrategy(
        **ROTATION_HYSTERESIS_V2_PARAMETERS,
        max_notional=gap_config.max_notional,
        max_risk_per_trade=gap_config.max_risk_per_trade,
    )
    bounded_v2 = {
        symbol: [bar for bar in bars if start <= _date_of_bar(bar) <= end]
        for symbol, bars in v2_bars.items()
    }
    v2_result = run_intraday_momentum_backtest(
        bounded_v2,
        strategy,
        cost,
        gap_config.initial_capital,
        entry_fill_model="open_pullback",
    )
    gap_result = run_gap_reversion_backtest(
        gap_bars, gap_config, start_date=start, end_date=end
    )
    hybrid = replay_earliest_signal(
        v2_result.trades, gap_result.trades, gap_config, cost
    )
    return v2_result.net_return_pct, hybrid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hybrid-state-research")
    parser.add_argument("--gap-config", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    config = load_gap_reversion_config(args.gap_config)
    v2_symbols = ("SOXL", "SOXS", "QQQ")
    gap_symbols = tuple(dict.fromkeys((*config.symbols, config.benchmark_symbol)))
    v2_bars = {
        symbol: load_bars(args.data_dir, symbol, "5 mins", duration="2 Y")
        for symbol in v2_symbols
    }
    gap_bars = {
        symbol: load_bars(args.data_dir, symbol, config.bar_size)
        for symbol in gap_symbols
    }
    periods = {
        "fold_1": (date(2025, 7, 17), date(2025, 10, 14)),
        "fold_2": (date(2025, 10, 15), date(2026, 1, 14)),
        "final_holdout": (date(2026, 4, 14), date(2026, 7, 14)),
        "full_2y": (date(2024, 7, 15), date(2026, 7, 14)),
    }
    payload: dict[str, object] = {}
    for name, (start, end) in periods.items():
        v2_return, hybrid = evaluate_period(
            v2_bars, gap_bars, config, start, end
        )
        item = asdict(hybrid)
        item["v2_return_pct"] = v2_return
        item["delta_pct_points"] = hybrid.net_return_pct - v2_return
        item["start"] = start.isoformat()
        item["end"] = end.isoformat()
        item["trades"] = [
            {**asdict(trade), "session_date": trade.session_date.isoformat()}
            for trade in hybrid.trades
        ]
        payload[name] = item
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
