from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .models import Bar, Quote
from .strategy import IntradayMomentumStrategy


@dataclass(frozen=True)
class BacktestCostModel:
    commission_per_order: float = 0.35
    slippage_bps: float = 1.0
    spread_bps: float = 1.0

    @property
    def per_side_bps(self) -> float:
        return self.slippage_bps + self.spread_bps / 2.0

    def buy_fill(self, raw_price: float) -> float:
        return raw_price * (1.0 + self.per_side_bps / 10_000.0)

    def sell_fill(self, raw_price: float) -> float:
        return raw_price * (1.0 - self.per_side_bps / 10_000.0)


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


def _group_bars_by_day(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[date, list[Bar]]]:
    grouped: dict[str, dict[date, list[Bar]]] = {}
    for symbol, bars in bars_by_symbol.items():
        daily: dict[date, list[Bar]] = defaultdict(list)
        for bar in bars:
            daily[bar.time.date()].append(bar)
        grouped[symbol.upper()] = daily
    return grouped


@dataclass(frozen=True)
class _PendingOrder:
    symbol: str
    quantity: int
    signal_index: int
    fill_index: int
    score: float


@dataclass(frozen=True)
class _OpenPosition:
    symbol: str
    quantity: int
    entry_price: float
    entry_index: int
    entry_date: date


def _select_signal(
    strategy: IntradayMomentumStrategy,
    daily_bars_by_symbol: dict[str, list[Bar]],
    benchmark_bars: list[Bar] | None,
    index: int,
) -> tuple[str, int, float] | None:
    candidates: list[tuple[float, str, int]] = []
    for symbol in strategy.symbols:
        bars = daily_bars_by_symbol.get(symbol.upper(), [])
        if len(bars) < strategy.min_bars or index >= len(bars):
            continue
        if index < max(strategy.slow_window, strategy.trend_window, strategy.trend_lookback):
            continue
        prefix = bars[: index + 1]
        quote = Quote(symbol=symbol, bid=prefix[-1].close, ask=prefix[-1].close, last=prefix[-1].close, close=prefix[-1].close)
        benchmark_prefix = benchmark_bars[: index + 1] if benchmark_bars is not None and index < len(benchmark_bars) else benchmark_bars
        decision = strategy.decide(symbol, quote, prefix, benchmark_bars=benchmark_prefix)
        if decision.signal and decision.quantity > 0:
            candidates.append((float(decision.meta.get("score", 0.0)), symbol.upper(), decision.quantity))
    if not candidates:
        return None
    score, symbol, quantity = max(candidates, key=lambda item: item[0])
    return symbol, quantity, score


def _exit_reason_from_decision(decision_meta: dict[str, object]) -> str:
    if decision_meta.get("stop_hit"):
        return "stop"
    if decision_meta.get("take_hit"):
        return "take"
    return "signal"


def run_intraday_momentum_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    strategy: IntradayMomentumStrategy | None = None,
    cost_model: BacktestCostModel | None = None,
    initial_capital: float = 1_000.0,
) -> BacktestResult:
    strategy = strategy or IntradayMomentumStrategy()
    cost_model = cost_model or BacktestCostModel()
    grouped = _group_bars_by_day(bars_by_symbol)
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

    for day in all_days:
        daily_bars_by_symbol = {symbol: grouped.get(symbol.upper(), {}).get(day, []) for symbol in strategy.symbols}
        benchmark_daily_bars = grouped.get(strategy.benchmark_symbol.upper(), {}).get(day, [])
        max_len = max((len(bars) for bars in daily_bars_by_symbol.values()), default=0)
        pending_order: _PendingOrder | None = None
        open_position: _OpenPosition | None = None
        day_closed = False

        for index in range(max_len):
            if pending_order is not None and index == pending_order.fill_index:
                bars = daily_bars_by_symbol.get(pending_order.symbol, [])
                if index < len(bars):
                    fill_bar = bars[index]
                    raw_entry_price = fill_bar.open
                    shares = min(
                        pending_order.quantity,
                        int(net_cash // cost_model.buy_fill(raw_entry_price)),
                        int(gross_cash // raw_entry_price),
                    )
                    if shares > 0:
                        gross_cash -= shares * raw_entry_price
                        net_cash -= shares * cost_model.buy_fill(raw_entry_price) + cost_model.commission_per_order
                        total_commission += cost_model.commission_per_order
                        total_spread_cost += shares * raw_entry_price * (cost_model.spread_bps / 10_000.0)
                        total_slippage_cost += shares * raw_entry_price * (cost_model.slippage_bps / 10_000.0)
                        open_position = _OpenPosition(
                            symbol=pending_order.symbol,
                            quantity=shares,
                            entry_price=raw_entry_price,
                            entry_index=index,
                            entry_date=fill_bar.time.date(),
                        )
                pending_order = None

            if open_position is not None:
                bars = daily_bars_by_symbol.get(open_position.symbol, [])
                if index < len(bars):
                    bar = bars[index]
                    exit_price: float | None = None
                    exit_reason: str | None = None
                    quote = Quote(symbol=open_position.symbol, bid=bar.close, ask=bar.close, last=bar.close, close=bar.close)
                    exit_decision = strategy.exit_decide(
                        open_position.symbol,
                        quote,
                        bars[: index + 1],
                        open_position.quantity,
                        open_position.entry_price,
                    )
                    if exit_decision.signal:
                        exit_price = bar.close
                        exit_reason = _exit_reason_from_decision(exit_decision.meta)

                    if exit_price is not None and exit_reason is not None:
                        gross_cash += open_position.quantity * exit_price
                        net_cash += (
                            open_position.quantity * cost_model.sell_fill(exit_price)
                            - cost_model.commission_per_order
                        )
                        gross_entry = open_position.entry_price
                        net_entry = cost_model.buy_fill(open_position.entry_price)
                        gross_exit = exit_price
                        net_exit = cost_model.sell_fill(exit_price)
                        gross_pnl = open_position.quantity * (gross_exit - gross_entry)
                        net_pnl = open_position.quantity * (net_exit - net_entry) - 2 * cost_model.commission_per_order
                        trade_count += 1
                        if net_pnl >= 0:
                            win_count += 1
                        else:
                            loss_count += 1
                        total_commission += cost_model.commission_per_order
                        total_spread_cost += open_position.quantity * exit_price * (cost_model.spread_bps / 10_000.0)
                        total_slippage_cost += open_position.quantity * exit_price * (cost_model.slippage_bps / 10_000.0)
                        trade_logs.append(
                            BacktestTrade(
                                symbol=open_position.symbol,
                                entry_date=open_position.entry_date,
                                exit_date=bar.time.date(),
                                shares=open_position.quantity,
                                gross_entry_price=gross_entry,
                                gross_exit_price=gross_exit,
                                net_entry_price=net_entry,
                                net_exit_price=net_exit,
                                exit_reason=exit_reason,
                                gross_pnl=gross_pnl,
                                net_pnl=net_pnl,
                            )
                        )
                        open_position = None
                        day_closed = True

            if day_closed:
                continue

            if open_position is None and pending_order is None:
                signal = _select_signal(strategy, daily_bars_by_symbol, benchmark_daily_bars, index)
                if signal is not None:
                    symbol, quantity, score = signal
                    pending_order = _PendingOrder(
                        symbol=symbol,
                        quantity=quantity,
                        signal_index=index,
                        fill_index=index + 1,
                        score=score,
                    )

        if open_position is not None:
            bars = daily_bars_by_symbol.get(open_position.symbol, [])
            if bars:
                last_bar = bars[-1]
                exit_price = last_bar.close
                gross_cash += open_position.quantity * exit_price
                net_cash += open_position.quantity * cost_model.sell_fill(exit_price) - cost_model.commission_per_order
                gross_entry = open_position.entry_price
                net_entry = cost_model.buy_fill(open_position.entry_price)
                gross_exit = exit_price
                net_exit = cost_model.sell_fill(exit_price)
                gross_pnl = open_position.quantity * (gross_exit - gross_entry)
                net_pnl = open_position.quantity * (net_exit - net_entry) - 2 * cost_model.commission_per_order
                trade_count += 1
                if net_pnl >= 0:
                    win_count += 1
                else:
                    loss_count += 1
                total_commission += cost_model.commission_per_order
                total_spread_cost += open_position.quantity * exit_price * (cost_model.spread_bps / 10_000.0)
                total_slippage_cost += open_position.quantity * exit_price * (cost_model.slippage_bps / 10_000.0)
                trade_logs.append(
                    BacktestTrade(
                        symbol=open_position.symbol,
                        entry_date=open_position.entry_date,
                        exit_date=last_bar.time.date(),
                        shares=open_position.quantity,
                        gross_entry_price=gross_entry,
                        gross_exit_price=gross_exit,
                        net_entry_price=net_entry,
                        net_exit_price=net_exit,
                        exit_reason="eod",
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                    )
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
