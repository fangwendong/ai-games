from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt
from statistics import pstdev
from typing import Iterable

from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.quality_low_vol_rotation import QualityLowVolRotationStrategy


@dataclass(frozen=True)
class BacktestSummary:
    strategy: str
    symbols: tuple[str, ...]
    start_date: str
    end_date: str
    starting_capital: float
    ending_capital: float
    total_return: float
    cagr: float
    annualized_volatility: float
    max_drawdown: float
    rebalance_count: int
    trade_count: int
    selected_symbol_counts: dict[str, int]


@dataclass(frozen=True)
class BacktestPoint:
    timestamp: str
    equity: float


def run_quality_low_vol_rotation_backtest(
    universe: dict[str, list[Bar]],
    strategy: QualityLowVolRotationStrategy,
    starting_capital: float = 10_000.0,
) -> tuple[BacktestSummary, tuple[BacktestPoint, ...]]:
    normalized = {symbol: _normalize_bars(bars) for symbol, bars in universe.items()}
    common_dates = _common_dates(normalized)
    if not common_dates:
        raise ValueError("backtest universe has no overlapping dates")

    rebalance_dates = _month_end_dates(common_dates)
    if not rebalance_dates:
        raise ValueError("backtest universe has no month-end rebalance points")

    selections = {
        rebalance_date: _select_at_date(strategy, normalized, rebalance_date)
        for rebalance_date in rebalance_dates
    }

    price_map = {
        symbol: {bar_date: close for bar_date, close in series}
        for symbol, series in normalized.items()
    }

    equity = starting_capital
    curve: list[BacktestPoint] = [BacktestPoint(timestamp=common_dates[0].isoformat(), equity=equity)]
    active_symbol: str | None = None
    selected_symbol_counts: Counter[str] = Counter()
    trade_count = 0

    for index in range(1, len(common_dates)):
        previous_date = common_dates[index - 1]
        current_date = common_dates[index]

        if previous_date in selections:
            next_symbol = selections[previous_date]
            if next_symbol != active_symbol:
                trade_count += 1
                active_symbol = next_symbol
                if active_symbol is not None:
                    selected_symbol_counts[active_symbol] += 1

        if active_symbol is not None:
            previous_price = price_map[active_symbol][previous_date]
            current_price = price_map[active_symbol][current_date]
            if previous_price > 0:
                equity *= current_price / previous_price

        curve.append(BacktestPoint(timestamp=current_date.isoformat(), equity=equity))

    total_return = (equity / starting_capital) - 1.0
    cagr = _cagr(starting_capital, equity, len(common_dates))
    annualized_volatility = _annualized_volatility([point.equity for point in curve])
    max_drawdown = _max_drawdown([point.equity for point in curve])

    summary = BacktestSummary(
        strategy=strategy.name,
        symbols=tuple(sorted(normalized)),
        start_date=common_dates[0].isoformat(),
        end_date=common_dates[-1].isoformat(),
        starting_capital=starting_capital,
        ending_capital=equity,
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        rebalance_count=len(rebalance_dates),
        trade_count=trade_count,
        selected_symbol_counts=dict(selected_symbol_counts),
    )
    return summary, tuple(curve)


def _normalize_bars(bars: list[Bar]) -> list[tuple[date, float]]:
    normalized: list[tuple[date, float]] = []
    for bar in bars:
        normalized.append((_parse_timestamp(bar.timestamp), bar.close))
    normalized.sort(key=lambda item: item[0])
    deduped: list[tuple[date, float]] = []
    for bar_date, close in normalized:
        if deduped and deduped[-1][0] == bar_date:
            deduped[-1] = (bar_date, close)
        else:
            deduped.append((bar_date, close))
    return deduped


def _parse_timestamp(timestamp: str) -> date:
    raw = timestamp.strip()
    for candidate in (raw, raw.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"unsupported bar timestamp: {timestamp!r}") from exc


def _common_dates(universe: dict[str, list[tuple[date, float]]]) -> list[date]:
    if not universe:
        return []
    common_dates = {bar_date for bar_date, _ in next(iter(universe.values()))}
    for series in universe.values():
        common_dates &= {bar_date for bar_date, _ in series}
    return sorted(common_dates)


def _month_end_dates(dates: list[date]) -> list[date]:
    rebalance_dates: list[date] = []
    for index, current in enumerate(dates):
        if index == len(dates) - 1:
            rebalance_dates.append(current)
            continue
        next_date = dates[index + 1]
        if current.month != next_date.month or current.year != next_date.year:
            rebalance_dates.append(current)
    return rebalance_dates


def _select_at_date(
    strategy: QualityLowVolRotationStrategy,
    universe: dict[str, list[tuple[date, float]]],
    rebalance_date: date,
) -> str | None:
    bars_by_symbol = {
        symbol: [
            Bar(timestamp=bar_date.isoformat(), close=close)
            for bar_date, close in series
            if bar_date <= rebalance_date
        ]
        for symbol, series in universe.items()
    }
    plan = strategy.build_plan(bars_by_symbol, {})
    return plan.selected_symbol


def _cagr(starting_capital: float, ending_capital: float, periods: int) -> float:
    if periods <= 1 or starting_capital <= 0 or ending_capital <= 0:
        return 0.0
    years = periods / 252.0
    if years <= 0:
        return 0.0
    return (ending_capital / starting_capital) ** (1.0 / years) - 1.0


def _annualized_volatility(equity_curve: Iterable[float]) -> float:
    values = list(equity_curve)
    if len(values) < 3:
        return 0.0
    returns = [(current / previous) - 1.0 for previous, current in zip(values, values[1:]) if previous > 0]
    if len(returns) < 2:
        return 0.0
    return pstdev(returns) * sqrt(252)


def _max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown
