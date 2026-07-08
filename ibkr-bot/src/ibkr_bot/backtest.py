from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt
from statistics import pstdev
from typing import Iterable, Literal

from ibkr_bot.strategy.base import Bar
from ibkr_bot.models import PositionSnapshot
from ibkr_bot.strategy.five_minute_momentum import FiveMinuteMomentumStrategy
from ibkr_bot.strategy.moving_average import MovingAverageCrossStrategy
from ibkr_bot.strategy.opening_range_breakout import OpeningRangeBreakoutStrategy
from ibkr_bot.strategy.quality_low_vol_rotation import QualityLowVolRotationStrategy
from ibkr_bot.strategy.volatility_managed import VolatilityManagedTrendStrategy
from ibkr_bot.strategy.vwap_pullback import VwapPullbackStrategy


@dataclass(frozen=True)
class BacktestSummary:
    strategy: str
    rebalance_frequency: str
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


@dataclass(frozen=True)
class WalkForwardBacktestResult:
    in_sample: BacktestSummary
    out_of_sample: BacktestSummary
    validation_split: float


@dataclass(frozen=True)
class _PendingOrder:
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    limit_price: float
    reason: str


def run_quality_low_vol_rotation_backtest(
    universe: dict[str, list[Bar]],
    strategy: QualityLowVolRotationStrategy,
    starting_capital: float = 10_000.0,
    rebalance_frequency: Literal["daily", "weekly", "monthly"] = "monthly",
) -> tuple[BacktestSummary, tuple[BacktestPoint, ...]]:
    normalized = {symbol: _normalize_bars(bars) for symbol, bars in universe.items()}
    common_dates = _common_dates(normalized)
    if not common_dates:
        raise ValueError("backtest universe has no overlapping dates")

    rebalance_dates = _rebalance_dates(common_dates, rebalance_frequency)
    if not rebalance_dates:
        raise ValueError(f"backtest universe has no {rebalance_frequency} rebalance points")

    price_map = {
        symbol: {bar_date: close for bar_date, close, _volume in series}
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

        if previous_date in rebalance_dates:
            next_symbol = _select_at_date(strategy, normalized, previous_date, active_symbol)
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
        rebalance_frequency=rebalance_frequency,
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


def run_five_minute_momentum_backtest(
    universe: dict[str, list[Bar]],
    strategy: FiveMinuteMomentumStrategy,
    starting_capital: float = 10_000.0,
) -> tuple[BacktestSummary, tuple[BacktestPoint, ...]]:
    return run_intraday_signal_backtest(universe, strategy, starting_capital=starting_capital)


def run_intraday_signal_backtest(
    universe: dict[str, list[Bar]],
    strategy: FiveMinuteMomentumStrategy | OpeningRangeBreakoutStrategy | VwapPullbackStrategy,
    starting_capital: float = 10_000.0,
    commission_per_trade: float = 0.0,
    slippage_bps: float = 0.0,
    track_from_index: int = 0,
) -> tuple[BacktestSummary, tuple[BacktestPoint, ...]]:
    normalized = {symbol: _normalize_intraday_bars(bars) for symbol, bars in universe.items()}
    common_timestamps = _common_timestamps(normalized)
    if not common_timestamps:
        raise ValueError("backtest universe has no overlapping intraday timestamps")
    track_from_index = max(0, min(int(track_from_index), len(common_timestamps) - 1))

    price_map = {
        symbol: {bar_timestamp: close for bar_timestamp, close, _volume in series}
        for symbol, series in normalized.items()
    }

    equity = starting_capital
    curve: list[BacktestPoint] = [
        BacktestPoint(timestamp=common_timestamps[track_from_index].isoformat(), equity=equity)
    ]
    active_symbol: str | None = None
    active_entry_price: float | None = None
    active_hold_bars = 0
    selected_symbol_counts: Counter[str] = Counter()
    trade_count = 0
    pending_order: _PendingOrder | None = None

    for index in range(track_from_index + 1, len(common_timestamps)):
        previous_timestamp = common_timestamps[index - 1]
        current_timestamp = common_timestamps[index]
        filled_this_bar = False

        if active_symbol is not None:
            previous_price = price_map[active_symbol][previous_timestamp]
            current_price = price_map[active_symbol][current_timestamp]
            if previous_price > 0:
                equity *= current_price / previous_price
            active_hold_bars += 1

        if active_symbol is not None:
            active_bars = _bars_until(normalized[active_symbol], current_timestamp)
            active_candidate = strategy.score(active_symbol, active_bars)
            exit_reason = None
            if active_candidate is not None and active_candidate.signal == "SELL":
                exit_reason = "signal"
            elif getattr(strategy, "flat_at_session_end", False) and previous_timestamp.date() != current_timestamp.date():
                exit_reason = "session_end"
            elif getattr(strategy, "max_hold_bars", 0) and active_hold_bars >= int(getattr(strategy, "max_hold_bars")):
                exit_reason = "max_hold"
            else:
                stop_loss_pct = float(getattr(strategy, "stop_loss_pct", 0.0) or 0.0)
                if stop_loss_pct > 0.0:
                    if active_entry_price is not None and current_price <= active_entry_price * (1.0 - stop_loss_pct):
                        exit_reason = "stop_loss"

            if exit_reason is not None:
                equity = _apply_trade_cost(
                    equity,
                    current_price,
                    commission_per_trade=commission_per_trade,
                    slippage_bps=slippage_bps,
                )
                trade_count += 1
                active_symbol = None
                active_entry_price = None
                active_hold_bars = 0
                pending_order = None
                filled_this_bar = True

        if not filled_this_bar and pending_order is not None:
            current_price = price_map[pending_order.symbol][current_timestamp]
            if _limit_can_fill(pending_order.side, pending_order.limit_price, current_price):
                equity = _apply_trade_cost(
                    equity,
                    current_price,
                    commission_per_trade=commission_per_trade,
                    slippage_bps=slippage_bps,
                )
                trade_count += 1
                if pending_order.side == "BUY":
                    active_symbol = pending_order.symbol
                    active_entry_price = current_price
                    active_hold_bars = 0
                    selected_symbol_counts[active_symbol] += 1
                else:
                    active_symbol = None
                    active_entry_price = None
                    active_hold_bars = 0
                pending_order = None
                filled_this_bar = True

        if not filled_this_bar:
            desired_order = _build_intraday_pending_order(
                strategy,
                normalized,
                price_map,
                current_timestamp,
                active_symbol,
            )
            pending_order = desired_order

        curve.append(BacktestPoint(timestamp=current_timestamp.isoformat(), equity=equity))

    total_return = (equity / starting_capital) - 1.0
    cagr = _cagr(starting_capital, equity, len(common_timestamps))
    annualized_volatility = _annualized_volatility([point.equity for point in curve])
    max_drawdown = _max_drawdown([point.equity for point in curve])

    summary = BacktestSummary(
        strategy=strategy.name,
        rebalance_frequency="5m",
        symbols=tuple(sorted(normalized)),
        start_date=common_timestamps[0].isoformat(),
        end_date=common_timestamps[-1].isoformat(),
        starting_capital=starting_capital,
        ending_capital=equity,
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        rebalance_count=len(common_timestamps),
        trade_count=trade_count,
        selected_symbol_counts=dict(selected_symbol_counts),
    )
    return summary, tuple(curve)


def run_intraday_walk_forward_backtest(
    universe: dict[str, list[Bar]],
    strategy: FiveMinuteMomentumStrategy | OpeningRangeBreakoutStrategy | VwapPullbackStrategy,
    starting_capital: float = 10_000.0,
    validation_split: float = 0.7,
    commission_per_trade: float = 0.0,
    slippage_bps: float = 0.0,
) -> WalkForwardBacktestResult:
    normalized = {symbol: _normalize_intraday_bars(bars) for symbol, bars in universe.items()}
    common_timestamps = _common_timestamps(normalized)
    if len(common_timestamps) < 4:
        raise ValueError("backtest universe has too few intraday timestamps for validation")
    if not 0.0 < validation_split < 1.0:
        raise ValueError("validation_split must be between 0 and 1")

    split_index = max(2, min(len(common_timestamps) - 1, int(len(common_timestamps) * validation_split)))
    warmup_bars = max(
        getattr(strategy, "pullback_window", 0),
        getattr(strategy, "trend_window", 0),
        getattr(strategy, "volume_window", 0),
        getattr(strategy, "slow_window", 0),
        getattr(strategy, "opening_range_bars", 0),
        1,
    ) + 1

    train_universe = {
        symbol: [Bar(timestamp=bar_timestamp.isoformat(), close=close, volume=volume) for bar_timestamp, close, volume in series[:split_index]]
        for symbol, series in normalized.items()
    }
    train_summary, _ = run_intraday_signal_backtest(
        train_universe,
        strategy,
        starting_capital=starting_capital,
        commission_per_trade=commission_per_trade,
        slippage_bps=slippage_bps,
    )

    validation_start = max(0, split_index - warmup_bars)
    validation_universe = {
        symbol: [
            Bar(timestamp=bar_timestamp.isoformat(), close=close, volume=volume)
            for bar_timestamp, close, volume in series[validation_start:]
        ]
        for symbol, series in normalized.items()
    }
    validation_summary, _ = run_intraday_signal_backtest(
        validation_universe,
        strategy,
        starting_capital=starting_capital,
        commission_per_trade=commission_per_trade,
        slippage_bps=slippage_bps,
        track_from_index=warmup_bars if validation_start == split_index - warmup_bars else split_index - validation_start,
    )

    return WalkForwardBacktestResult(
        in_sample=train_summary,
        out_of_sample=validation_summary,
        validation_split=validation_split,
    )


def run_trend_backtest(
    bars: list[Bar],
    strategy: MovingAverageCrossStrategy | VolatilityManagedTrendStrategy,
    starting_capital: float = 10_000.0,
) -> tuple[BacktestSummary, tuple[BacktestPoint, ...]]:
    normalized = _normalize_bars(bars)
    if not normalized:
        raise ValueError("trend backtest universe has no bars")

    equity = starting_capital
    shares = 0.0
    curve: list[BacktestPoint] = [BacktestPoint(timestamp=normalized[0][0].isoformat(), equity=equity)]
    trade_count = 0

    for index in range(1, len(normalized)):
        current_history = [
            Bar(timestamp=bar_date.isoformat(), close=close, volume=volume)
            for bar_date, close, volume in normalized[: index + 1]
        ]
        current_date, current_price, _current_volume = normalized[index]
        previous_date, previous_price, _previous_volume = normalized[index - 1]
        position = PositionSnapshot(symbol="SPY", quantity=shares, market_price=previous_price) if shares > 0 else None
        intent = strategy.generate("SPY", current_history, position)

        if intent is not None:
            if intent.side.value == "BUY" and shares == 0:
                shares = equity / current_price if current_price > 0 else 0.0
                trade_count += 1
            elif intent.side.value == "SELL" and shares > 0:
                trade_count += 1
                shares = 0.0

        if shares > 0 and previous_price > 0:
            equity *= current_price / previous_price

        curve.append(BacktestPoint(timestamp=current_date.isoformat(), equity=equity))

    total_return = (equity / starting_capital) - 1.0
    cagr = _cagr(starting_capital, equity, len(normalized))
    annualized_volatility = _annualized_volatility([point.equity for point in curve])
    max_drawdown = _max_drawdown([point.equity for point in curve])

    summary = BacktestSummary(
        strategy=strategy.name,
        rebalance_frequency="trend",
        symbols=("SPY",),
        start_date=normalized[0][0].isoformat(),
        end_date=normalized[-1][0].isoformat(),
        starting_capital=starting_capital,
        ending_capital=equity,
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        rebalance_count=0,
        trade_count=trade_count,
        selected_symbol_counts={"SPY": trade_count} if trade_count else {},
    )
    return summary, tuple(curve)


def _normalize_bars(bars: list[Bar]) -> list[tuple[date, float, float]]:
    normalized: list[tuple[date, float, float]] = []
    for bar in bars:
        normalized.append((_parse_timestamp(bar.timestamp), bar.close, float(bar.volume or 0.0)))
    normalized.sort(key=lambda item: item[0])
    deduped: list[tuple[date, float, float]] = []
    for bar_date, close, volume in normalized:
        if deduped and deduped[-1][0] == bar_date:
            deduped[-1] = (bar_date, close, volume)
        else:
            deduped.append((bar_date, close, volume))
    return deduped


def _normalize_intraday_bars(bars: list[Bar]) -> list[tuple[datetime, float, float]]:
    normalized: list[tuple[datetime, float, float]] = []
    for bar in bars:
        normalized.append((_parse_intraday_timestamp(bar.timestamp), bar.close, float(bar.volume or 0.0)))
    normalized.sort(key=lambda item: item[0])
    deduped: list[tuple[datetime, float, float]] = []
    for bar_timestamp, close, volume in normalized:
        if deduped and deduped[-1][0] == bar_timestamp:
            deduped[-1] = (bar_timestamp, close, volume)
        else:
            deduped.append((bar_timestamp, close, volume))
    return deduped


def _bars_until(series: list[tuple[datetime, float, float]], timestamp: datetime) -> list[Bar]:
    return [
        Bar(timestamp=bar_timestamp.isoformat(), close=close, volume=volume)
        for bar_timestamp, close, volume in series
        if bar_timestamp <= timestamp
    ]


def _build_intraday_pending_order(
    strategy: FiveMinuteMomentumStrategy | OpeningRangeBreakoutStrategy | VwapPullbackStrategy,
    universe: dict[str, list[tuple[datetime, float, float]]],
    price_map: dict[str, dict[datetime, float]],
    current_timestamp: datetime,
    active_symbol: str | None,
) -> _PendingOrder | None:
    if active_symbol is not None:
        active_bars = _bars_until(universe[active_symbol], current_timestamp)
        active_candidate = strategy.score(active_symbol, active_bars)
        if active_candidate is None or active_candidate.signal != "SELL":
            return None
        current_price = price_map[active_symbol][current_timestamp]
        return _PendingOrder(
            symbol=active_symbol,
            side="SELL",
            quantity=1,
            limit_price=round(current_price * 1.001, 2),
            reason=f"{strategy.name}: lost VWAP",
        )

    next_symbol = _select_intraday_entry_at_timestamp(strategy, universe, current_timestamp, None)
    if next_symbol is None:
        return None
    current_price = price_map[next_symbol][current_timestamp]
    return _PendingOrder(
        symbol=next_symbol,
        side="BUY",
        quantity=1,
        limit_price=round(current_price * 0.999, 2),
        reason=f"{strategy.name}: entry signal",
    )


def _limit_can_fill(side: Literal["BUY", "SELL"], limit_price: float, current_price: float) -> bool:
    if side == "BUY":
        return current_price <= limit_price
    if side == "SELL":
        return current_price >= limit_price
    return False


def _apply_trade_cost(
    equity: float,
    reference_price: float,
    *,
    commission_per_trade: float,
    slippage_bps: float,
) -> float:
    if equity <= 0:
        return equity
    cost = max(0.0, float(commission_per_trade))
    if reference_price > 0 and slippage_bps > 0:
        cost += reference_price * (float(slippage_bps) / 10_000.0)
    return max(0.0, equity - cost)


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


def _parse_intraday_timestamp(timestamp: str) -> datetime:
    raw = timestamp.strip()
    for candidate in (raw, raw.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d %H:%M:%S %Z", "%Y%m%d %H:%M:%S%z"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    raise ValueError(f"unsupported intraday bar timestamp: {timestamp!r}")


def _common_dates(universe: dict[str, list[tuple[date, float, float]]]) -> list[date]:
    if not universe:
        return []
    common_dates = {bar_date for bar_date, _close, _volume in next(iter(universe.values()))}
    for series in universe.values():
        common_dates &= {bar_date for bar_date, _close, _volume in series}
    return sorted(common_dates)


def _common_timestamps(universe: dict[str, list[tuple[datetime, float, float]]]) -> list[datetime]:
    if not universe:
        return []
    common_timestamps = {bar_timestamp for bar_timestamp, _close, _volume in next(iter(universe.values()))}
    for series in universe.values():
        common_timestamps &= {bar_timestamp for bar_timestamp, _close, _volume in series}
    return sorted(common_timestamps)


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


def _rebalance_dates(dates: list[date], frequency: Literal["daily", "weekly", "monthly"]) -> list[date]:
    if frequency == "daily":
        return list(dates)
    if frequency == "weekly":
        return _week_end_dates(dates)
    if frequency == "monthly":
        return _month_end_dates(dates)
    raise ValueError(f"unsupported rebalance frequency: {frequency}")


def _week_end_dates(dates: list[date]) -> list[date]:
    rebalance_dates: list[date] = []
    for index, current in enumerate(dates):
        if index == len(dates) - 1:
            rebalance_dates.append(current)
            continue
        next_date = dates[index + 1]
        if current.isocalendar()[:2] != next_date.isocalendar()[:2]:
            rebalance_dates.append(current)
    return rebalance_dates


def _select_at_date(
    strategy: QualityLowVolRotationStrategy,
    universe: dict[str, list[tuple[date, float, float]]],
    rebalance_date: date,
    active_symbol: str | None = None,
) -> str | None:
    bars_by_symbol = {
        symbol: [
            Bar(timestamp=bar_date.isoformat(), close=close, volume=volume)
            for bar_date, close, volume in series
            if bar_date <= rebalance_date
        ]
        for symbol, series in universe.items()
    }
    positions = {}
    if active_symbol is not None and active_symbol in bars_by_symbol and bars_by_symbol[active_symbol]:
        positions[active_symbol] = PositionSnapshot(
            symbol=active_symbol,
            quantity=1,
            market_price=bars_by_symbol[active_symbol][-1].close,
        )
    plan = strategy.build_plan(bars_by_symbol, positions)
    return plan.selected_symbol


def _select_intraday_entry_at_timestamp(
    strategy: FiveMinuteMomentumStrategy | OpeningRangeBreakoutStrategy | VwapPullbackStrategy,
    universe: dict[str, list[tuple[datetime, float, float]]],
    rebalance_timestamp: datetime,
    active_symbol: str | None = None,
    excluded_symbol: str | None = None,
) -> str | None:
    scored = []
    for symbol, series in universe.items():
        if excluded_symbol is not None and symbol == excluded_symbol:
            continue
        bars = [
            Bar(timestamp=bar_timestamp.isoformat(), close=close, volume=volume)
            for bar_timestamp, close, volume in series
            if bar_timestamp <= rebalance_timestamp
        ]
        candidate = strategy.score(symbol, bars)
        if candidate is not None and candidate.signal == "BUY":
            scored.append(candidate)
    if not scored:
        return None
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    if active_symbol is not None:
        current_candidate = next((candidate for candidate in scored if candidate.symbol == active_symbol), None)
        if current_candidate is not None and current_candidate.score >= scored[0].score - getattr(strategy, "switch_score_margin", 0.0):
            return active_symbol
    return scored[0].symbol


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
