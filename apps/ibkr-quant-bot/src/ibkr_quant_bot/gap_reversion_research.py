from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

from .backtest import BacktestCostModel
from .historical_cache import load_bars
from .models import Bar


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GapReversionConfig:
    """Research-only long gap-down recovery strategy."""

    strategy_version: str
    symbols: tuple[str, ...]
    bar_size: str = "5 mins"
    statistics_lookback: int = 14
    observation_minutes: int = 15
    minimum_gap_down_pct: float = 0.015
    minimum_gap_atr: float = 0.4
    minimum_average_daily_volume: float = 5_000_000.0
    minimum_price: float = 10.0
    maximum_ranked_candidates: int = 3
    recovery_confirm_bars: int = 2
    maximum_opening_relative_volume: float | None = None
    entry_cutoff_et_minutes: int = 11 * 60
    exit_signal_et_minutes: int = 15 * 60 + 50
    atr_stop_multiple: float = 0.5
    benchmark_symbol: str = "QQQ"
    maximum_benchmark_gap_down_pct: float = 0.015
    max_notional: float = 4_000.0
    max_risk_per_trade: float = 120.0
    initial_capital: float = 4_000.0
    commission_per_order: float = 1.0
    slippage_bps: float = 1.0
    spread_bps: float = 1.0

    def __post_init__(self) -> None:
        if not self.strategy_version or not self.symbols:
            raise ValueError("strategy_version and symbols are required")
        if self.statistics_lookback < 2:
            raise ValueError("statistics_lookback must be at least 2")
        if self.observation_minutes <= 0 or self.observation_minutes % 5:
            raise ValueError("observation_minutes must be a positive multiple of 5")
        if self.minimum_gap_down_pct <= 0 or self.minimum_gap_atr <= 0:
            raise ValueError("gap thresholds must be positive")
        if self.recovery_confirm_bars < 1:
            raise ValueError("recovery_confirm_bars must be positive")
        if (
            self.maximum_opening_relative_volume is not None
            and self.maximum_opening_relative_volume <= 0
        ):
            raise ValueError("maximum_opening_relative_volume must be positive")
        if self.entry_cutoff_et_minutes >= self.exit_signal_et_minutes:
            raise ValueError("entry cutoff must precede the exit signal")


@dataclass(frozen=True)
class GapReversionTrade:
    symbol: str
    session_date: date
    gap_down_pct: float
    gap_atr: float
    entry_time: datetime
    exit_time: datetime
    shares: int
    raw_entry_price: float
    raw_exit_price: float
    stop_distance: float
    exit_reason: str
    net_pnl: float
    opening_relative_volume: float = 0.0


@dataclass(frozen=True)
class GapReversionResult:
    strategy_version: str
    start_date: date | None
    end_date: date | None
    initial_capital: float
    ending_capital: float
    net_return_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate_pct: float
    max_drawdown: float
    trades: tuple[GapReversionTrade, ...]


@dataclass(frozen=True)
class _PriorStats:
    previous_close: float
    average_daily_volume: float
    average_true_range: float
    average_opening_volume: float


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    rows: tuple[Bar, ...]
    previous_close: float
    average_true_range: float
    gap_down_pct: float
    gap_atr: float
    opening_relative_volume: float


def load_gap_reversion_config(path: str | Path) -> GapReversionConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["symbols"] = tuple(str(value).upper() for value in payload["symbols"])
    payload["benchmark_symbol"] = str(payload["benchmark_symbol"]).upper()
    return GapReversionConfig(**payload)


def _session_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(NEW_YORK).date()


def _et_minutes(value: datetime) -> int:
    local = value if value.tzinfo is None else value.astimezone(NEW_YORK)
    return local.hour * 60 + local.minute


def _group_bars(bars: list[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = {}
    for bar in sorted(bars, key=lambda value: value.time):
        grouped.setdefault(_session_date(bar.time), []).append(bar)
    return {day: tuple(rows) for day, rows in grouped.items()}


def _prior_stats(
    grouped: dict[date, tuple[Bar, ...]], lookback: int, opening_bar_count: int
) -> dict[date, _PriorStats]:
    days = sorted(grouped)
    daily_volume = {day: sum(bar.volume for bar in grouped[day]) for day in days}
    true_range: dict[date, float] = {}
    previous_close: float | None = None
    for day in days:
        rows = grouped[day]
        high = max(bar.high for bar in rows)
        low = min(bar.low for bar in rows)
        true_range[day] = (
            high - low
            if previous_close is None
            else max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        previous_close = rows[-1].close

    result: dict[date, _PriorStats] = {}
    for index, day in enumerate(days):
        prior = days[max(0, index - lookback) : index]
        if len(prior) < lookback:
            continue
        result[day] = _PriorStats(
            previous_close=grouped[prior[-1]][-1].close,
            average_daily_volume=fmean(daily_volume[value] for value in prior),
            average_true_range=fmean(true_range[value] for value in prior),
            average_opening_volume=fmean(
                sum(bar.volume for bar in grouped[value][:opening_bar_count])
                for value in prior
            ),
        )
    return result


def _vwap_prefix(rows: tuple[Bar, ...]) -> tuple[float, ...]:
    cumulative_value = 0.0
    cumulative_volume = 0.0
    values: list[float] = []
    for bar in rows:
        cumulative_value += ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
        cumulative_volume += bar.volume
        values.append(
            cumulative_value / cumulative_volume if cumulative_volume else bar.close
        )
    return tuple(values)


def _entry(
    candidate: _Candidate, config: GapReversionConfig
) -> tuple[int, Bar] | None:
    start_index = config.observation_minutes // 5
    vwaps = _vwap_prefix(candidate.rows)
    for index in range(start_index, len(candidate.rows)):
        bar = candidate.rows[index]
        if _et_minutes(bar.time) > config.entry_cutoff_et_minutes:
            break
        window_start = index - config.recovery_confirm_bars + 1
        if window_start < 0:
            continue
        recovery = candidate.rows[window_start : index + 1]
        if any(row.close <= row.open for row in recovery):
            continue
        if any(
            recovery[offset].close <= recovery[offset - 1].close
            for offset in range(1, len(recovery))
        ):
            continue
        if bar.close <= vwaps[index] or bar.close >= candidate.previous_close:
            continue
        next_index = index + 1
        if next_index >= len(candidate.rows):
            return None
        fill = candidate.rows[next_index]
        if _et_minutes(fill.time) <= config.entry_cutoff_et_minutes:
            return next_index, fill
    return None


def run_gap_reversion_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    config: GapReversionConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> GapReversionResult:
    loaded = tuple(dict.fromkeys((*config.symbols, config.benchmark_symbol)))
    grouped = {symbol: _group_bars(bars_by_symbol.get(symbol, [])) for symbol in loaded}
    opening_bar_count = config.observation_minutes // 5
    stats = {
        symbol: _prior_stats(
            grouped[symbol], config.statistics_lookback, opening_bar_count
        )
        for symbol in loaded
    }
    sessions = sorted({day for symbol in config.symbols for day in grouped[symbol]})
    sessions = [
        day
        for day in sessions
        if (start_date is None or day >= start_date)
        and (end_date is None or day <= end_date)
    ]
    cost = BacktestCostModel(
        commission_per_order=config.commission_per_order,
        slippage_bps=config.slippage_bps,
        spread_bps=config.spread_bps,
    )
    capital = config.initial_capital
    peak = capital
    max_drawdown = 0.0
    trades: list[GapReversionTrade] = []

    for session in sessions:
        benchmark_rows = grouped[config.benchmark_symbol].get(session)
        benchmark_prior = stats[config.benchmark_symbol].get(session)
        if benchmark_rows is None or benchmark_prior is None:
            continue
        benchmark_gap = (
            benchmark_rows[0].open / benchmark_prior.previous_close - 1.0
        )
        if benchmark_gap < -config.maximum_benchmark_gap_down_pct:
            continue

        candidates: list[_Candidate] = []
        for symbol in config.symbols:
            rows = grouped[symbol].get(session)
            prior = stats[symbol].get(session)
            if rows is None or prior is None or len(rows) < 5:
                continue
            opening_price = rows[0].open
            if opening_price < config.minimum_price:
                continue
            if prior.average_daily_volume < config.minimum_average_daily_volume:
                continue
            gap_down_pct = 1.0 - opening_price / prior.previous_close
            gap_amount = prior.previous_close - opening_price
            if gap_down_pct < config.minimum_gap_down_pct:
                continue
            if prior.average_true_range <= 0:
                continue
            gap_atr = gap_amount / prior.average_true_range
            if gap_atr < config.minimum_gap_atr:
                continue
            opening_volume = sum(bar.volume for bar in rows[:opening_bar_count])
            opening_relative_volume = (
                opening_volume / prior.average_opening_volume
                if prior.average_opening_volume > 0
                else 0.0
            )
            if (
                config.maximum_opening_relative_volume is not None
                and opening_relative_volume
                > config.maximum_opening_relative_volume
            ):
                continue
            candidates.append(
                _Candidate(
                    symbol=symbol,
                    rows=rows,
                    previous_close=prior.previous_close,
                    average_true_range=prior.average_true_range,
                    gap_down_pct=gap_down_pct,
                    gap_atr=gap_atr,
                    opening_relative_volume=opening_relative_volume,
                )
            )

        ranked = sorted(candidates, key=lambda value: (-value.gap_atr, value.symbol))[
            : config.maximum_ranked_candidates
        ]
        entries: list[tuple[datetime, float, str, _Candidate, int, Bar]] = []
        for candidate in ranked:
            entry = _entry(candidate, config)
            if entry is None:
                continue
            entry_index, fill = entry
            entries.append(
                (
                    fill.time,
                    -candidate.gap_atr,
                    candidate.symbol,
                    candidate,
                    entry_index,
                    fill,
                )
            )
        if not entries:
            continue
        _, _, _, candidate, entry_index, entry_bar = min(entries)
        raw_entry = entry_bar.open
        if raw_entry >= candidate.previous_close:
            continue
        stop_distance = candidate.average_true_range * config.atr_stop_multiple
        risk_shares = int(config.max_risk_per_trade // stop_distance)
        notional_shares = int(config.max_notional // raw_entry)
        cash_shares = int(
            max(0.0, capital - config.commission_per_order)
            // cost.buy_fill(raw_entry)
        )
        shares = min(risk_shares, notional_shares, cash_shares)
        if shares <= 0:
            continue

        raw_exit = candidate.rows[-1].close
        exit_time = candidate.rows[-1].time
        exit_reason = "eod"
        stop_price = raw_entry - stop_distance
        for index in range(entry_index, len(candidate.rows)):
            bar = candidate.rows[index]
            reason: str | None = None
            if bar.close <= stop_price:
                reason = "stop"
            elif bar.close >= candidate.previous_close:
                reason = "gap_fill"
            elif _et_minutes(bar.time) >= config.exit_signal_et_minutes:
                reason = "eod"
            if reason is None:
                continue
            next_index = index + 1
            if next_index < len(candidate.rows):
                raw_exit = candidate.rows[next_index].open
                exit_time = candidate.rows[next_index].time
            else:
                raw_exit = bar.close
                exit_time = bar.time
            exit_reason = reason
            break

        net_pnl = (
            shares * (cost.sell_fill(raw_exit) - cost.buy_fill(raw_entry))
            - cost.commission(shares, side="BUY")
            - cost.commission(shares, side="SELL")
        )
        capital += net_pnl
        peak = max(peak, capital)
        max_drawdown = max(max_drawdown, peak - capital)
        trades.append(
            GapReversionTrade(
                symbol=candidate.symbol,
                session_date=session,
                gap_down_pct=candidate.gap_down_pct,
                gap_atr=candidate.gap_atr,
                entry_time=entry_bar.time,
                exit_time=exit_time,
                shares=shares,
                raw_entry_price=raw_entry,
                raw_exit_price=raw_exit,
                stop_distance=stop_distance,
                exit_reason=exit_reason,
                net_pnl=net_pnl,
                opening_relative_volume=candidate.opening_relative_volume,
            )
        )

    wins = sum(trade.net_pnl >= 0 for trade in trades)
    return GapReversionResult(
        strategy_version=config.strategy_version,
        start_date=sessions[0] if sessions else start_date,
        end_date=sessions[-1] if sessions else end_date,
        initial_capital=config.initial_capital,
        ending_capital=capital,
        net_return_pct=(capital / config.initial_capital - 1.0) * 100.0,
        trade_count=len(trades),
        win_count=wins,
        loss_count=len(trades) - wins,
        win_rate_pct=(wins / len(trades) * 100.0) if trades else 0.0,
        max_drawdown=max_drawdown,
        trades=tuple(trades),
    )


def evaluate_chronological_splits(
    bars_by_symbol: dict[str, list[Bar]], config: GapReversionConfig
) -> dict[str, GapReversionResult]:
    sessions = sorted(
        {
            _session_date(bar.time)
            for symbol in config.symbols
            for bar in bars_by_symbol.get(symbol, [])
        }
    )[config.statistics_lookback :]
    if len(sessions) < 15:
        raise ValueError("chronological evaluation requires at least 15 sessions")
    train_size = int(len(sessions) * 0.6)
    validation_size = int(len(sessions) * 0.2)
    holdout_start = train_size + validation_size
    periods = {
        "full": (sessions[0], sessions[-1]),
        "train": (sessions[0], sessions[train_size - 1]),
        "validation": (sessions[train_size], sessions[holdout_start - 1]),
        "holdout": (sessions[holdout_start], sessions[-1]),
    }
    return {
        name: run_gap_reversion_backtest(
            bars_by_symbol, config, start_date=start, end_date=end
        )
        for name, (start, end) in periods.items()
    }


def _payload(result: GapReversionResult, include_trades: bool) -> dict[str, object]:
    payload = asdict(result)
    payload["start_date"] = result.start_date.isoformat() if result.start_date else None
    payload["end_date"] = result.end_date.isoformat() if result.end_date else None
    payload["trades"] = [
        {
            **asdict(trade),
            "session_date": trade.session_date.isoformat(),
            "entry_time": trade.entry_time.isoformat(),
            "exit_time": trade.exit_time.isoformat(),
        }
        for trade in result.trades
    ]
    if not include_trades:
        payload.pop("trades")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gap-reversion-research")
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--chronological-split", action="store_true")
    parser.add_argument("--include-trades", action="store_true")
    args = parser.parse_args(argv)
    config = load_gap_reversion_config(args.config)
    loaded = tuple(dict.fromkeys((*config.symbols, config.benchmark_symbol)))
    bars = {symbol: load_bars(args.data_dir, symbol, config.bar_size) for symbol in loaded}
    if args.chronological_split:
        results = evaluate_chronological_splits(bars, config)
        payload = {
            name: _payload(result, args.include_trades)
            for name, result in results.items()
        }
    else:
        payload = _payload(run_gap_reversion_backtest(bars, config), args.include_trades)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
