from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from inspect import signature
from math import erfc, sqrt
from statistics import fmean, stdev
from zoneinfo import ZoneInfo

from .models import Bar, Quote
from .strategy import IntradayMomentumStrategy


@dataclass(frozen=True)
class BacktestCostModel:
    commission_per_order: float = 1.0
    slippage_bps: float = 1.0
    spread_bps: float = 1.0
    commission_per_share: float = 0.0
    minimum_commission_per_order: float = 0.0
    sell_fee_per_share: float = 0.0

    @property
    def per_side_bps(self) -> float:
        return self.slippage_bps + self.spread_bps / 2.0

    def buy_fill(self, raw_price: float) -> float:
        return raw_price * (1.0 + self.per_side_bps / 10_000.0)

    def sell_fill(self, raw_price: float) -> float:
        return raw_price * (1.0 - self.per_side_bps / 10_000.0)

    def commission(self, shares: int, *, side: str) -> float:
        variable = self.commission_per_share * shares
        base = max(
            self.commission_per_order,
            self.minimum_commission_per_order,
            variable,
        )
        if side.upper() == "SELL":
            base += self.sell_fee_per_share * shares
        return base


@dataclass(frozen=True)
class ProfitLockRule:
    """Close-based trailing profit lock used only when explicitly enabled."""

    activation_pct: float
    drawdown_pct: float

    def __post_init__(self) -> None:
        if self.activation_pct <= 0:
            raise ValueError("activation_pct must be positive")
        if self.drawdown_pct <= 0:
            raise ValueError("drawdown_pct must be positive")


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    entry_date: date
    exit_date: date
    shares: int
    gross_entry_price: float
    gross_exit_price: float
    net_entry_price: float
    net_exit_price: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    entry_time: datetime | None = None


@dataclass(frozen=True)
class BacktestResult:
    initial_capital: float
    gross_ending_capital: float
    net_ending_capital: float
    gross_return_pct: float
    net_return_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    total_commission: float
    total_slippage_cost: float
    total_spread_cost: float
    trades: tuple[BacktestTrade, ...] = ()


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    result: BacktestResult


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    holdout_start: date
    holdout_end: date
    holdout: BacktestResult


@dataclass(frozen=True)
class ParameterStabilityResult:
    name: str
    fold_count: int
    mean_oos_return_pct: float
    min_oos_return_pct: float
    max_oos_return_pct: float
    positive_fold_ratio: float
    approximate_two_sided_p_value: float | None
    bonferroni_p_value: float | None


def _group_bars_by_day(
    bars_by_symbol: dict[str, list[Bar]],
) -> dict[str, dict[date, list[Bar]]]:
    grouped: dict[str, dict[date, list[Bar]]] = {}
    for symbol, bars in bars_by_symbol.items():
        daily: dict[date, list[Bar]] = defaultdict(list)
        for bar in sorted(bars, key=lambda item: _time_key(item.time)):
            daily[_session_date(bar.time)].append(bar)
        grouped[symbol.upper()] = daily
    return grouped


def _bars_by_time(bars: list[Bar]) -> dict[datetime, Bar]:
    return {_time_key(bar.time): bar for bar in bars}


@dataclass(frozen=True)
class _PendingOrder:
    symbol: str
    quantity: int
    signal_time: datetime
    fill_time: datetime
    score: float


@dataclass(frozen=True)
class _PendingExit:
    signal_time: datetime
    fill_time: datetime
    reason: str


@dataclass(frozen=True)
class _OpenPosition:
    symbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    entry_date: date
    entry_commission: float
    protective_stop_price: float | None = None
    protective_take_price: float | None = None


NEW_YORK = ZoneInfo("America/New_York")


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


def _time_key(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _session_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(NEW_YORK).date()


def validate_historical_bar_coverage(
    bars_by_symbol: dict[str, list[Bar]],
    *,
    recent_sessions: int = 2,
    bar_size: str = "5 mins",
) -> dict[str, object]:
    """Fail closed when the newest cached 5-minute sessions are incomplete."""
    if recent_sessions < 1:
        raise ValueError("recent_sessions must be positive")
    if not bars_by_symbol:
        raise ValueError("historical preflight requires at least one symbol")
    bar_seconds = _bar_size_seconds(bar_size)
    if 390 * 60 % bar_seconds != 0 or 210 * 60 % bar_seconds != 0:
        raise ValueError(f"unsupported bar size for session coverage checks: {bar_size}")
    regular_count = (390 * 60) // bar_seconds
    early_close_count = (210 * 60) // bar_seconds

    grouped: dict[str, dict[date, list[Bar]]] = {}
    latest_by_symbol: dict[str, date] = {}
    for raw_symbol, bars in bars_by_symbol.items():
        symbol = raw_symbol.upper()
        if not bars:
            raise ValueError(f"historical preflight found no bars for {symbol}")
        sessions: dict[date, list[Bar]] = defaultdict(list)
        for bar in bars:
            sessions[_session_date(bar.time)].append(bar)
        grouped[symbol] = sessions
        latest_by_symbol[symbol] = max(sessions)

    latest_dates = set(latest_by_symbol.values())
    if len(latest_dates) != 1:
        detail = ", ".join(
            f"{symbol}={session.isoformat()}"
            for symbol, session in sorted(latest_by_symbol.items())
        )
        raise ValueError(f"historical preflight latest-session mismatch: {detail}")

    common_sessions = sorted(
        set.intersection(*(set(sessions) for sessions in grouped.values()))
    )
    if len(common_sessions) < recent_sessions:
        raise ValueError(
            "historical preflight needs at least "
            f"{recent_sessions} common sessions; found {len(common_sessions)}"
        )

    checked = common_sessions[-recent_sessions:]
    counts: dict[str, dict[str, int]] = {}
    for session in checked:
        session_key = session.isoformat()
        timeline_by_symbol: dict[str, tuple[datetime, ...]] = {}
        counts[session_key] = {}
        for symbol, sessions in grouped.items():
            bars = sessions[session]
            timeline = tuple(sorted(_time_key(bar.time) for bar in bars))
            if len(timeline) != len(set(timeline)):
                raise ValueError(
                    f"historical preflight found duplicate {symbol} bars on {session_key}"
                )
            if len(timeline) not in {early_close_count, regular_count}:
                raise ValueError(
                    "historical preflight expected "
                    f"{regular_count} regular-session bars or {early_close_count} "
                    f"early-close bars for {symbol} on {session_key}; found {len(timeline)}"
                )
            gaps = [
                (later - earlier).total_seconds()
                for earlier, later in zip(timeline, timeline[1:])
            ]
            if any(gap != bar_seconds for gap in gaps):
                raise ValueError(
                    f"historical preflight found a non-{bar_size} gap for {symbol} on {session_key}"
                )
            timeline_by_symbol[symbol] = timeline
            counts[session_key][symbol] = len(timeline)
        reference_symbol = sorted(timeline_by_symbol)[0]
        reference = timeline_by_symbol[reference_symbol]
        for symbol, timeline in timeline_by_symbol.items():
            if timeline != reference:
                raise ValueError(
                    "historical preflight timeline mismatch on "
                    f"{session_key}: {reference_symbol} versus {symbol}"
                )

    latest = next(iter(latest_dates))
    return {
        "status": "passed",
        "latest_common_session": latest.isoformat(),
        "checked_sessions": [session.isoformat() for session in checked],
        "bar_counts": counts,
    }


def _available_time(bar: Bar, availability_delay: timedelta) -> datetime:
    return _time_key(bar.time) + availability_delay


def _prefix_available_at(
    bars: list[Bar],
    current_time: datetime,
    availability_delay: timedelta,
) -> list[Bar]:
    return [
        bar
        for bar in bars
        if _available_time(bar, availability_delay) <= current_time
    ]


def _first_bar_time_at_or_after(
    bars: list[Bar], current_time: datetime
) -> datetime | None:
    return next(
        (_time_key(bar.time) for bar in bars if _time_key(bar.time) >= current_time),
        None,
    )


def _fill_price(fill_bar: Bar, *, mode: str, side: str) -> float:
    normalized_mode = mode.replace("-", "_")
    normalized_side = side.upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported fill side: {side}")
    if normalized_mode == "next_bar_open":
        return fill_bar.open
    if normalized_mode == "open_pullback":
        if normalized_side == "BUY":
            pullback = max(0.0, fill_bar.open - fill_bar.low)
            return max(fill_bar.low, fill_bar.open - 0.2 * pullback)
        return fill_bar.open
    if normalized_mode == "worst_case":
        return fill_bar.high if normalized_side == "BUY" else fill_bar.low
    raise ValueError(f"unsupported entry fill mode: {mode}")


def _eod_exit_price(fill_bar: Bar, *, mode: str) -> float:
    if mode.replace("-", "_") == "worst_case":
        return fill_bar.low
    return fill_bar.close


def _select_signal(
    strategy: IntradayMomentumStrategy,
    daily_bars_by_symbol: dict[str, list[Bar]],
    benchmark_bars: list[Bar] | None,
    current_time: datetime,
    availability_delay: timedelta,
) -> tuple[str, int, float] | None:
    candidates: list[tuple[float, str, int]] = []
    for symbol in strategy.symbols:
        bars = daily_bars_by_symbol.get(symbol.upper(), [])
        prefix = _prefix_available_at(bars, current_time, availability_delay)
        if len(prefix) < strategy.min_bars:
            continue
        if _available_time(prefix[-1], availability_delay) != current_time:
            continue
        quote = Quote(
            symbol=symbol,
            bid=prefix[-1].close,
            ask=prefix[-1].close,
            last=prefix[-1].close,
            close=prefix[-1].close,
        )
        benchmark_prefix = (
            _prefix_available_at(
                benchmark_bars, current_time, availability_delay
            )
            if benchmark_bars is not None
            else None
        )
        decision = strategy.decide(
            symbol, quote, prefix, benchmark_bars=benchmark_prefix
        )
        if decision.signal and decision.quantity > 0:
            candidates.append(
                (
                    float(decision.meta.get("score", 0.0)),
                    symbol.upper(),
                    decision.quantity,
                )
            )
    if not candidates:
        return None
    score, symbol, quantity = max(candidates, key=lambda item: item[0])
    return symbol, quantity, score


def _exit_decision(
    strategy: IntradayMomentumStrategy,
    symbol: str,
    quote: Quote,
    bars: list[Bar],
    quantity: int,
    average_cost: float,
    benchmark_bars: list[Bar],
):
    parameters = signature(strategy.exit_decide).parameters
    if "benchmark_bars" in parameters:
        return strategy.exit_decide(
            symbol,
            quote,
            bars,
            quantity,
            average_cost,
            benchmark_bars=benchmark_bars,
        )
    return strategy.exit_decide(symbol, quote, bars, quantity, average_cost)


def _exit_reason_from_decision(decision_meta: dict[str, object]) -> str:
    if decision_meta.get("stop_hit"):
        return "stop"
    if decision_meta.get("take_hit"):
        return "take"
    return "signal"


def _protective_prices(
    strategy: IntradayMomentumStrategy,
    symbol: str,
    average_cost: float,
    bars: list[Bar],
) -> tuple[float | None, float | None]:
    protective_prices = getattr(strategy, "protective_prices", None)
    if not callable(protective_prices):
        return None, None
    stop_price, take_price = protective_prices(symbol, average_cost, bars)
    return round(float(stop_price), 2), round(float(take_price), 2)


def _protective_fill(
    position: _OpenPosition, bar: Bar, *, mode: str
) -> tuple[float, str] | None:
    """Model the broker-side sell OCA after the entry bar has completed.

    A sell stop gaps down to the bar open, while a sell limit receives opening
    price improvement. Five-minute OHLC cannot reveal which order fired first
    when both levels trade in one bar, so the stop wins as the conservative
    assumption.
    """
    stop_price = position.protective_stop_price
    take_price = position.protective_take_price
    stop_hit = stop_price is not None and bar.low <= stop_price
    take_hit = take_price is not None and bar.high >= take_price
    if mode.replace("-", "_") == "worst_case":
        if stop_hit:
            return bar.low, "protective_stop"
        if take_hit:
            return bar.low, "protective_take"
        return None
    if stop_hit:
        return min(bar.open, stop_price), "protective_stop"
    if take_hit:
        return max(bar.open, take_price), "protective_take"
    return None


def run_intraday_momentum_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    strategy: IntradayMomentumStrategy | None = None,
    cost_model: BacktestCostModel | None = None,
    initial_capital: float = 1_000.0,
    profit_lock_rule: ProfitLockRule | None = None,
    simulate_protective_oca: bool = True,
    entry_fill_model: str = "next_bar_open",
    fill_bars_by_symbol: dict[str, list[Bar]] | None = None,
    signal_bar_size: str = "5 mins",
) -> BacktestResult:
    strategy = strategy or IntradayMomentumStrategy()
    cost_model = cost_model or BacktestCostModel()
    signal_availability_delay = timedelta(
        seconds=_bar_size_seconds(signal_bar_size)
    )
    if profit_lock_rule is None:
        activation_pct = getattr(strategy, "profit_lock_activation_pct", None)
        drawdown_pct = getattr(strategy, "profit_lock_drawdown_pct", None)
        if activation_pct is not None and drawdown_pct is not None:
            profit_lock_rule = ProfitLockRule(activation_pct, drawdown_pct)
    grouped = _group_bars_by_day(bars_by_symbol)
    fill_grouped = _group_bars_by_day(fill_bars_by_symbol or bars_by_symbol)
    all_days = sorted({day for daily in grouped.values() for day in daily})

    gross_cash = initial_capital
    net_cash = initial_capital
    trade_count = 0
    win_count = 0
    loss_count = 0
    total_commission = 0.0
    total_slippage_cost = 0.0
    total_spread_cost = 0.0
    trade_logs: list[BacktestTrade] = []

    def close_position(
        position: _OpenPosition, raw_exit_price: float, exit_date: date, reason: str
    ) -> None:
        nonlocal gross_cash, net_cash, trade_count, win_count, loss_count
        nonlocal total_commission, total_slippage_cost, total_spread_cost
        gross_cash += position.quantity * raw_exit_price
        exit_commission = cost_model.commission(position.quantity, side="SELL")
        net_cash += (
            position.quantity * cost_model.sell_fill(raw_exit_price) - exit_commission
        )
        gross_entry = position.entry_price
        net_entry = cost_model.buy_fill(position.entry_price)
        gross_exit = raw_exit_price
        net_exit = cost_model.sell_fill(raw_exit_price)
        gross_pnl = position.quantity * (gross_exit - gross_entry)
        net_pnl = (
            position.quantity * (net_exit - net_entry)
            - position.entry_commission
            - exit_commission
        )
        trade_count += 1
        if net_pnl >= 0:
            win_count += 1
        else:
            loss_count += 1
        total_commission += exit_commission
        total_spread_cost += (
            position.quantity * raw_exit_price * (cost_model.spread_bps / 10_000.0)
        )
        total_slippage_cost += (
            position.quantity * raw_exit_price * (cost_model.slippage_bps / 10_000.0)
        )
        trade_logs.append(
            BacktestTrade(
                symbol=position.symbol,
                entry_date=position.entry_date,
                exit_date=exit_date,
                shares=position.quantity,
                gross_entry_price=gross_entry,
                gross_exit_price=gross_exit,
                net_entry_price=net_entry,
                net_exit_price=net_exit,
                exit_reason=reason,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                entry_time=position.entry_time,
            )
        )

    for day in all_days:
        daily_signal_bars_by_symbol = {
            symbol: grouped.get(symbol.upper(), {}).get(day, [])
            for symbol in strategy.symbols
        }
        daily_fill_bars_by_symbol = {
            symbol: fill_grouped.get(symbol.upper(), {}).get(day, [])
            for symbol in strategy.symbols
        }
        benchmark_daily_bars = grouped.get(strategy.benchmark_symbol.upper(), {}).get(
            day, []
        )
        signal_bars_by_time = {
            symbol: {
                _available_time(bar, signal_availability_delay): bar
                for bar in bars
            }
            for symbol, bars in daily_signal_bars_by_symbol.items()
        }
        fill_bars_by_time = {
            symbol: _bars_by_time(bars)
            for symbol, bars in daily_fill_bars_by_symbol.items()
        }
        signal_timeline = sorted(
            {moment for rows in signal_bars_by_time.values() for moment in rows}
        )
        fill_timeline = sorted(
            {moment for rows in fill_bars_by_time.values() for moment in rows}
        )
        timeline = sorted(set(signal_timeline) | set(fill_timeline))
        signal_timeline_set = set(signal_timeline)
        pending_order: _PendingOrder | None = None
        pending_exit: _PendingExit | None = None
        open_position: _OpenPosition | None = None
        peak_close: float | None = None
        day_closed = False

        def fill_pending_exit_at(current_time: datetime) -> None:
            nonlocal pending_exit, open_position, peak_close, day_closed
            if (
                pending_exit is None
                or current_time != pending_exit.fill_time
                or open_position is None
            ):
                return
            fill_bar = fill_bars_by_time.get(open_position.symbol, {}).get(
                current_time
            )
            if fill_bar is not None:
                raw_exit_price = _fill_price(
                    fill_bar, mode=entry_fill_model, side="SELL"
                )
                close_position(
                    open_position,
                    raw_exit_price,
                    _session_date(fill_bar.time),
                    pending_exit.reason,
                )
                open_position = None
                peak_close = None
                day_closed = True
            pending_exit = None

        def fill_pending_order_at(current_time: datetime) -> None:
            nonlocal pending_order, open_position, peak_close
            nonlocal gross_cash, net_cash
            nonlocal total_commission, total_slippage_cost, total_spread_cost
            if pending_order is None or current_time != pending_order.fill_time:
                return
            fill_bar = fill_bars_by_time.get(pending_order.symbol, {}).get(
                current_time
            )
            if fill_bar is not None:
                raw_entry_price = _fill_price(
                    fill_bar, mode=entry_fill_model, side="BUY"
                )
                shares = min(
                    pending_order.quantity,
                    int(net_cash // cost_model.buy_fill(raw_entry_price)),
                    int(gross_cash // raw_entry_price),
                )
                if shares > 0:
                    entry_commission = cost_model.commission(shares, side="BUY")
                    gross_cash -= shares * raw_entry_price
                    net_cash -= (
                        shares * cost_model.buy_fill(raw_entry_price)
                        + entry_commission
                    )
                    total_commission += entry_commission
                    total_spread_cost += (
                        shares
                        * raw_entry_price
                        * (cost_model.spread_bps / 10_000.0)
                    )
                    total_slippage_cost += (
                        shares
                        * raw_entry_price
                        * (cost_model.slippage_bps / 10_000.0)
                    )
                    signal_bars = _prefix_available_at(
                        daily_signal_bars_by_symbol.get(
                            pending_order.symbol, []
                        ),
                        pending_order.signal_time,
                        signal_availability_delay,
                    )
                    protective_stop_price: float | None = None
                    protective_take_price: float | None = None
                    if simulate_protective_oca:
                        (
                            protective_stop_price,
                            protective_take_price,
                        ) = _protective_prices(
                            strategy,
                            pending_order.symbol,
                            cost_model.buy_fill(raw_entry_price),
                            signal_bars,
                        )
                    open_position = _OpenPosition(
                        symbol=pending_order.symbol,
                        quantity=shares,
                        entry_price=raw_entry_price,
                        entry_time=current_time,
                        entry_date=_session_date(fill_bar.time),
                        entry_commission=entry_commission,
                        protective_stop_price=protective_stop_price,
                        protective_take_price=protective_take_price,
                    )
                    peak_close = max(raw_entry_price, fill_bar.close)
            pending_order = None

        for current_time in timeline:
            if day_closed:
                continue

            fill_pending_exit_at(current_time)
            if day_closed:
                continue
            fill_pending_order_at(current_time)

            if (
                open_position is not None
                and simulate_protective_oca
                and current_time > open_position.entry_time
            ):
                bar = fill_bars_by_time.get(open_position.symbol, {}).get(current_time)
                protective_fill = (
                    _protective_fill(open_position, bar, mode=entry_fill_model)
                    if bar is not None
                    else None
                )
                if protective_fill is not None:
                    fill_price, reason = protective_fill
                    close_position(
                        open_position,
                        fill_price,
                        _session_date(bar.time),
                        reason,
                    )
                    open_position = None
                    pending_exit = None
                    peak_close = None
                    day_closed = True

            if day_closed:
                continue

            if current_time in signal_timeline_set:
                if open_position is not None and pending_exit is None:
                    signal_bars = daily_signal_bars_by_symbol.get(open_position.symbol, [])
                    signal_bar = signal_bars_by_time.get(open_position.symbol, {}).get(
                        current_time
                    )
                    if signal_bar is not None:
                        peak_close = max(
                            peak_close or open_position.entry_price, signal_bar.close
                        )
                        prefix = _prefix_available_at(
                            signal_bars,
                            current_time,
                            signal_availability_delay,
                        )
                        benchmark_prefix = _prefix_available_at(
                            benchmark_daily_bars,
                            current_time,
                            signal_availability_delay,
                        )
                        quote = Quote(
                            symbol=open_position.symbol,
                            bid=signal_bar.close,
                            ask=signal_bar.close,
                            last=signal_bar.close,
                            close=signal_bar.close,
                        )
                        exit_decision = _exit_decision(
                            strategy,
                            open_position.symbol,
                            quote,
                            prefix,
                            open_position.quantity,
                            open_position.entry_price,
                            benchmark_prefix,
                        )
                        if exit_decision.signal:
                            fill_time = _first_bar_time_at_or_after(
                                daily_fill_bars_by_symbol.get(open_position.symbol, []),
                                current_time,
                            )
                            if fill_time is not None:
                                pending_exit = _PendingExit(
                                    signal_time=current_time,
                                    fill_time=fill_time,
                                    reason=_exit_reason_from_decision(
                                        exit_decision.meta
                                    ),
                                )
                        elif (
                            profit_lock_rule is not None
                            and peak_close
                            >= open_position.entry_price
                            * (1.0 + profit_lock_rule.activation_pct)
                            and signal_bar.close
                            <= peak_close * (1.0 - profit_lock_rule.drawdown_pct)
                        ):
                            fill_time = _first_bar_time_at_or_after(
                                daily_fill_bars_by_symbol.get(open_position.symbol, []),
                                current_time,
                            )
                            if fill_time is not None:
                                pending_exit = _PendingExit(
                                    signal_time=current_time,
                                    fill_time=fill_time,
                                    reason="profit_lock",
                                )

                if open_position is None and pending_order is None and pending_exit is None:
                    signal = _select_signal(
                        strategy,
                        daily_signal_bars_by_symbol,
                        benchmark_daily_bars,
                        current_time,
                        signal_availability_delay,
                    )
                    if signal is not None:
                        symbol, quantity, score = signal
                        fill_time = _first_bar_time_at_or_after(
                            daily_fill_bars_by_symbol.get(symbol, []), current_time
                        )
                        if fill_time is not None:
                            pending_order = _PendingOrder(
                                symbol=symbol,
                                quantity=quantity,
                                signal_time=current_time,
                                fill_time=fill_time,
                                score=score,
                            )

                fill_pending_exit_at(current_time)
                if not day_closed:
                    fill_pending_order_at(current_time)

        if open_position is not None:
            bars = daily_signal_bars_by_symbol.get(open_position.symbol, [])
            if bars:
                last_bar = bars[-1]
                close_position(
                    open_position, _eod_exit_price(last_bar, mode=entry_fill_model), _session_date(last_bar.time), "eod"
                )

    return BacktestResult(
        initial_capital=initial_capital,
        gross_ending_capital=gross_cash,
        net_ending_capital=net_cash,
        gross_return_pct=(gross_cash / initial_capital - 1.0) * 100.0,
        net_return_pct=(net_cash / initial_capital - 1.0) * 100.0,
        trade_count=trade_count,
        win_count=win_count,
        loss_count=loss_count,
        total_commission=total_commission,
        total_slippage_cost=total_slippage_cost,
        total_spread_cost=total_spread_cost,
        trades=tuple(trade_logs),
    )


def _filter_days(
    bars_by_symbol: dict[str, list[Bar]], days: set[date]
) -> dict[str, list[Bar]]:
    return {
        symbol: [bar for bar in bars if _session_date(bar.time) in days]
        for symbol, bars in bars_by_symbol.items()
    }


def evaluate_fixed_strategy_walk_forward(
    bars_by_symbol: dict[str, list[Bar]],
    strategy: IntradayMomentumStrategy,
    cost_model: BacktestCostModel,
    initial_capital: float,
    *,
    train_days: int,
    test_days: int,
    step_days: int,
    holdout_days: int,
    entry_fill_model: str = "next_bar_open",
    fill_bars_by_symbol: dict[str, list[Bar]] | None = None,
    signal_bar_size: str = "5 mins",
) -> WalkForwardResult:
    """Evaluate fixed parameters on chronological, non-overlapping OOS slices.

    The training windows are reported as provenance only. This function never
    selects parameters on them, which keeps the final holdout untouched and
    avoids presenting overlapping lookbacks as independent experiments.
    """
    all_days = sorted(
        {_session_date(bar.time) for bars in bars_by_symbol.values() for bar in bars}
    )
    for name, value in {
        "train_days": train_days,
        "test_days": test_days,
        "step_days": step_days,
        "holdout_days": holdout_days,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    required = train_days + test_days + holdout_days
    if len(all_days) < required:
        raise ValueError(
            f"need at least {required} trading days, received {len(all_days)}"
        )

    development_days = all_days[:-holdout_days]
    folds = _evaluate_folds(
        bars_by_symbol,
        strategy,
        cost_model,
        initial_capital,
        development_days,
        train_days,
        test_days,
        step_days,
        entry_fill_model,
        fill_bars_by_symbol,
        signal_bar_size,
    )
    if not folds:
        raise ValueError("walk-forward settings produced no out-of-sample folds")

    holdout = all_days[-holdout_days:]
    holdout_result = run_intraday_momentum_backtest(
        _filter_days(bars_by_symbol, set(holdout)),
        strategy=strategy,
        cost_model=cost_model,
        initial_capital=initial_capital,
        entry_fill_model=entry_fill_model,
        fill_bars_by_symbol=(
            _filter_days(fill_bars_by_symbol, set(holdout))
            if fill_bars_by_symbol is not None
            else None
        ),
        signal_bar_size=signal_bar_size,
    )
    return WalkForwardResult(
        folds=tuple(folds),
        holdout_start=holdout[0],
        holdout_end=holdout[-1],
        holdout=holdout_result,
    )


def _evaluate_folds(
    bars_by_symbol: dict[str, list[Bar]],
    strategy: IntradayMomentumStrategy,
    cost_model: BacktestCostModel,
    initial_capital: float,
    development_days: list[date],
    train_days: int,
    test_days: int,
    step_days: int,
    entry_fill_model: str,
    fill_bars_by_symbol: dict[str, list[Bar]] | None,
    signal_bar_size: str,
) -> list[WalkForwardFold]:
    if step_days < test_days:
        raise ValueError(
            "step_days must be at least test_days so OOS folds do not overlap"
        )
    folds: list[WalkForwardFold] = []
    start = 0
    while start + train_days + test_days <= len(development_days):
        training = development_days[start : start + train_days]
        testing = development_days[start + train_days : start + train_days + test_days]
        result = run_intraday_momentum_backtest(
            _filter_days(bars_by_symbol, set(testing)),
            strategy=strategy,
            cost_model=cost_model,
            initial_capital=initial_capital,
            entry_fill_model=entry_fill_model,
            fill_bars_by_symbol=(
                _filter_days(fill_bars_by_symbol, set(testing))
                if fill_bars_by_symbol is not None
                else None
            ),
            signal_bar_size=signal_bar_size,
        )
        folds.append(
            WalkForwardFold(
                train_start=training[0],
                train_end=training[-1],
                test_start=testing[0],
                test_end=testing[-1],
                result=result,
            )
        )
        start += step_days
    return folds


def evaluate_parameter_stability(
    bars_by_symbol: dict[str, list[Bar]],
    strategies: dict[str, IntradayMomentumStrategy],
    cost_model: BacktestCostModel,
    initial_capital: float,
    *,
    train_days: int,
    test_days: int,
    step_days: int,
    holdout_days: int,
    entry_fill_model: str = "next_bar_open",
    fill_bars_by_symbol: dict[str, list[Bar]] | None = None,
    signal_bar_size: str = "5 mins",
) -> tuple[ParameterStabilityResult, ...]:
    """Compare nearby fixed parameter sets without touching final holdout bars."""
    all_days = sorted(
        {_session_date(bar.time) for bars in bars_by_symbol.values() for bar in bars}
    )
    development_days = all_days[:-holdout_days]
    raw: list[tuple[str, list[float]]] = []
    for name, strategy in strategies.items():
        folds = _evaluate_folds(
            bars_by_symbol,
            strategy,
            cost_model,
            initial_capital,
            development_days,
            train_days,
            test_days,
            step_days,
            entry_fill_model,
            fill_bars_by_symbol,
            signal_bar_size,
        )
        raw.append((name, [fold.result.net_return_pct for fold in folds]))

    comparison_count = max(1, len(raw))
    results: list[ParameterStabilityResult] = []
    for name, returns in raw:
        approximate_p: float | None = None
        if len(returns) >= 2 and stdev(returns) > 0:
            z_score = fmean(returns) / (stdev(returns) / sqrt(len(returns)))
            approximate_p = erfc(abs(z_score) / sqrt(2.0))
        results.append(
            ParameterStabilityResult(
                name=name,
                fold_count=len(returns),
                mean_oos_return_pct=fmean(returns) if returns else 0.0,
                min_oos_return_pct=min(returns, default=0.0),
                max_oos_return_pct=max(returns, default=0.0),
                positive_fold_ratio=(sum(value > 0 for value in returns) / len(returns))
                if returns
                else 0.0,
                approximate_two_sided_p_value=approximate_p,
                bonferroni_p_value=(
                    min(1.0, approximate_p * comparison_count)
                    if approximate_p is not None
                    else None
                ),
            )
        )
    return tuple(results)
