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
class OrbResearchConfig:
    """Research-only configuration for a long-only Stocks-in-Play ORB."""

    strategy_version: str
    symbols: tuple[str, ...]
    bar_size: str = "5 mins"
    opening_range_minutes: int = 5
    relative_volume_lookback: int = 14
    minimum_relative_volume: float = 1.0
    minimum_average_daily_volume: float = 1_000_000.0
    minimum_atr: float = 0.5
    minimum_price: float = 5.0
    maximum_ranked_candidates: int = 3
    entry_cutoff_et_minutes: int = 11 * 60
    exit_signal_et_minutes: int = 15 * 60 + 50
    atr_stop_multiple: float = 0.1
    max_notional: float = 4_000.0
    max_risk_per_trade: float = 120.0
    initial_capital: float = 4_000.0
    commission_per_order: float = 1.0
    slippage_bps: float = 1.0
    spread_bps: float = 1.0
    benchmark_symbol: str | None = None
    benchmark_filter: str = "none"

    def __post_init__(self) -> None:
        if not self.strategy_version:
            raise ValueError("strategy_version is required")
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        if self.opening_range_minutes <= 0 or self.opening_range_minutes % 5:
            raise ValueError("opening_range_minutes must be a positive multiple of 5")
        if self.relative_volume_lookback < 2:
            raise ValueError("relative_volume_lookback must be at least 2")
        if self.maximum_ranked_candidates < 1:
            raise ValueError("maximum_ranked_candidates must be positive")
        if self.entry_cutoff_et_minutes >= self.exit_signal_et_minutes:
            raise ValueError("entry cutoff must precede the exit signal")
        if self.atr_stop_multiple <= 0:
            raise ValueError("atr_stop_multiple must be positive")
        if self.benchmark_filter not in {
            "none",
            "bullish_opening_range",
            "above_previous_close",
            "bullish_and_above_previous_close",
        }:
            raise ValueError(f"unsupported benchmark_filter: {self.benchmark_filter}")
        if self.benchmark_filter != "none" and not self.benchmark_symbol:
            raise ValueError("benchmark_symbol is required for a benchmark filter")


@dataclass(frozen=True)
class OrbTrade:
    symbol: str
    session_date: date
    relative_volume: float
    entry_time: datetime
    exit_time: datetime
    shares: int
    raw_entry_price: float
    raw_exit_price: float
    stop_distance: float
    exit_reason: str
    net_pnl: float


@dataclass(frozen=True)
class OrbBacktestResult:
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
    trades: tuple[OrbTrade, ...]


@dataclass(frozen=True)
class _DailyStats:
    average_daily_volume: float
    average_true_range: float
    average_opening_volume: float


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    relative_volume: float
    opening_high: float
    stop_distance: float
    bars: tuple[Bar, ...]


def load_orb_research_config(path: str | Path) -> OrbResearchConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["symbols"] = tuple(str(item).upper() for item in payload["symbols"])
    if payload.get("benchmark_symbol"):
        payload["benchmark_symbol"] = str(payload["benchmark_symbol"]).upper()
    return OrbResearchConfig(**payload)


def _session_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(NEW_YORK).date()


def _et_minutes(value: datetime) -> int:
    local = value if value.tzinfo is None else value.astimezone(NEW_YORK)
    return local.hour * 60 + local.minute


def _group_bars(bars: list[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = {}
    for bar in sorted(bars, key=lambda item: item.time):
        grouped.setdefault(_session_date(bar.time), []).append(bar)
    return {day: tuple(rows) for day, rows in grouped.items()}


def _true_range(rows: tuple[Bar, ...], previous_close: float | None) -> float:
    high = max(row.high for row in rows)
    low = min(row.low for row in rows)
    if previous_close is None:
        return high - low
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _daily_stats(
    grouped: dict[date, tuple[Bar, ...]],
    opening_bar_count: int,
    lookback: int,
) -> dict[date, _DailyStats]:
    days = sorted(grouped)
    daily_volume = {day: sum(row.volume for row in grouped[day]) for day in days}
    true_range: dict[date, float] = {}
    previous_close: float | None = None
    for day in days:
        rows = grouped[day]
        true_range[day] = _true_range(rows, previous_close)
        previous_close = rows[-1].close

    result: dict[date, _DailyStats] = {}
    for index, day in enumerate(days):
        prior = days[max(0, index - lookback) : index]
        eligible = [
            prior_day
            for prior_day in prior
            if len(grouped[prior_day]) >= opening_bar_count
        ]
        if len(eligible) < lookback:
            continue
        result[day] = _DailyStats(
            average_daily_volume=fmean(daily_volume[item] for item in eligible),
            average_true_range=fmean(true_range[item] for item in eligible),
            average_opening_volume=fmean(
                sum(row.volume for row in grouped[item][:opening_bar_count])
                for item in eligible
            ),
        )
    return result


def _next_bar(rows: tuple[Bar, ...], index: int) -> Bar | None:
    next_index = index + 1
    return rows[next_index] if next_index < len(rows) else None


def _benchmark_allows_long(
    grouped: dict[date, tuple[Bar, ...]],
    session: date,
    opening_bar_count: int,
    filter_name: str,
) -> bool:
    if filter_name == "none":
        return True
    rows = grouped.get(session)
    if rows is None or len(rows) < opening_bar_count:
        return False
    days = sorted(day for day in grouped if day < session)
    if not days:
        return False
    opening = rows[:opening_bar_count]
    bullish = opening[-1].close > opening[0].open
    above_previous_close = opening[-1].close > grouped[days[-1]][-1].close
    if filter_name == "bullish_opening_range":
        return bullish
    if filter_name == "above_previous_close":
        return above_previous_close
    return bullish and above_previous_close


def _entry_for_candidate(
    candidate: _Candidate, config: OrbResearchConfig
) -> tuple[int, Bar] | None:
    opening_bar_count = config.opening_range_minutes // 5
    for index in range(opening_bar_count, len(candidate.bars)):
        bar = candidate.bars[index]
        if _et_minutes(bar.time) > config.entry_cutoff_et_minutes:
            break
        if bar.close <= candidate.opening_high:
            continue
        fill = _next_bar(candidate.bars, index)
        if fill is not None and _et_minutes(fill.time) <= config.entry_cutoff_et_minutes:
            return index + 1, fill
    return None


def run_orb_research_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    config: OrbResearchConfig,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> OrbBacktestResult:
    """Run an isolated, long-only and close-confirmed ORB backtest.

    The signal uses only completed bars. Both entries and stop exits fill at the
    following bar open, avoiding optimistic same-bar breakout/stop fills.
    """

    opening_bar_count = config.opening_range_minutes // 5
    loaded_symbols = tuple(
        dict.fromkeys(
            (*config.symbols, *((config.benchmark_symbol,) if config.benchmark_symbol else ()))
        )
    )
    grouped = {
        symbol: _group_bars(bars_by_symbol.get(symbol, []))
        for symbol in loaded_symbols
    }
    stats = {
        symbol: _daily_stats(
            grouped[symbol], opening_bar_count, config.relative_volume_lookback
        )
        for symbol in config.symbols
    }
    sessions = sorted(
        {day for daily in grouped.values() for day in daily}
    )
    selected_sessions = [
        session
        for session in sessions
        if (start_date is None or session >= start_date)
        and (end_date is None or session <= end_date)
    ]
    cost = BacktestCostModel(
        commission_per_order=config.commission_per_order,
        slippage_bps=config.slippage_bps,
        spread_bps=config.spread_bps,
    )
    capital = config.initial_capital
    peak = capital
    max_drawdown = 0.0
    trades: list[OrbTrade] = []

    for session in selected_sessions:
        if config.benchmark_symbol and not _benchmark_allows_long(
            grouped[config.benchmark_symbol],
            session,
            opening_bar_count,
            config.benchmark_filter,
        ):
            continue
        candidates: list[_Candidate] = []
        for symbol in config.symbols:
            rows = grouped[symbol].get(session)
            prior = stats[symbol].get(session)
            if rows is None or prior is None or len(rows) < opening_bar_count + 2:
                continue
            opening = rows[:opening_bar_count]
            opening_price = opening[0].open
            if opening_price < config.minimum_price:
                continue
            if prior.average_daily_volume < config.minimum_average_daily_volume:
                continue
            if prior.average_true_range < config.minimum_atr:
                continue
            if opening[-1].close <= opening[0].open:
                continue
            opening_volume = sum(row.volume for row in opening)
            if prior.average_opening_volume <= 0:
                continue
            relative_volume = opening_volume / prior.average_opening_volume
            if relative_volume < config.minimum_relative_volume:
                continue
            candidates.append(
                _Candidate(
                    symbol=symbol,
                    relative_volume=relative_volume,
                    opening_high=max(row.high for row in opening),
                    stop_distance=prior.average_true_range
                    * config.atr_stop_multiple,
                    bars=rows,
                )
            )

        ranked = sorted(
            candidates, key=lambda item: (-item.relative_volume, item.symbol)
        )[: config.maximum_ranked_candidates]
        entries: list[tuple[datetime, float, str, _Candidate, int, Bar]] = []
        for candidate in ranked:
            entry = _entry_for_candidate(candidate, config)
            if entry is not None:
                entry_index, fill = entry
                entries.append(
                    (
                        fill.time,
                        -candidate.relative_volume,
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
        risk_shares = int(config.max_risk_per_trade // candidate.stop_distance)
        notional_shares = int(config.max_notional // raw_entry)
        cash_shares = int(max(0.0, capital - config.commission_per_order) // cost.buy_fill(raw_entry))
        shares = min(risk_shares, notional_shares, cash_shares)
        if shares <= 0:
            continue

        raw_exit = candidate.bars[-1].close
        exit_time = candidate.bars[-1].time
        exit_reason = "eod"
        stop_price = raw_entry - candidate.stop_distance
        for index in range(entry_index, len(candidate.bars)):
            bar = candidate.bars[index]
            if bar.close <= stop_price:
                fill = _next_bar(candidate.bars, index)
                if fill is not None:
                    raw_exit = fill.open
                    exit_time = fill.time
                    exit_reason = "stop"
                break
            if _et_minutes(bar.time) >= config.exit_signal_et_minutes:
                fill = _next_bar(candidate.bars, index)
                if fill is not None:
                    raw_exit = fill.open
                    exit_time = fill.time
                else:
                    raw_exit = bar.close
                    exit_time = bar.time
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
            OrbTrade(
                symbol=candidate.symbol,
                session_date=session,
                relative_volume=candidate.relative_volume,
                entry_time=entry_bar.time,
                exit_time=exit_time,
                shares=shares,
                raw_entry_price=raw_entry,
                raw_exit_price=raw_exit,
                stop_distance=candidate.stop_distance,
                exit_reason=exit_reason,
                net_pnl=net_pnl,
            )
        )

    wins = sum(trade.net_pnl >= 0 for trade in trades)
    return OrbBacktestResult(
        strategy_version=config.strategy_version,
        start_date=selected_sessions[0] if selected_sessions else start_date,
        end_date=selected_sessions[-1] if selected_sessions else end_date,
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
    bars_by_symbol: dict[str, list[Bar]],
    config: OrbResearchConfig,
) -> dict[str, OrbBacktestResult]:
    """Evaluate fixed parameters on 60/20/20 chronological periods."""

    sessions = sorted(
        {
            _session_date(bar.time)
            for symbol in config.symbols
            for bar in bars_by_symbol.get(symbol, [])
        }
    )
    usable = sessions[config.relative_volume_lookback :]
    if len(usable) < 15:
        raise ValueError("chronological evaluation requires at least 15 usable sessions")
    train_size = max(1, int(len(usable) * 0.60))
    validation_size = max(1, int(len(usable) * 0.20))
    validation_start = train_size
    holdout_start = min(len(usable) - 1, train_size + validation_size)
    periods = {
        "full": (usable[0], usable[-1]),
        "train": (usable[0], usable[train_size - 1]),
        "validation": (usable[validation_start], usable[holdout_start - 1]),
        "holdout": (usable[holdout_start], usable[-1]),
    }
    return {
        name: run_orb_research_backtest(
            bars_by_symbol, config, start_date=start, end_date=end
        )
        for name, (start, end) in periods.items()
    }


def _result_payload(result: OrbBacktestResult) -> dict[str, object]:
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
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orb-research-backtest")
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument(
        "--chronological-split",
        action="store_true",
        help="report fixed-parameter 60/20/20 train/validation/holdout periods",
    )
    args = parser.parse_args(argv)

    config = load_orb_research_config(args.config)
    loaded_symbols = tuple(
        dict.fromkeys(
            (*config.symbols, *((config.benchmark_symbol,) if config.benchmark_symbol else ()))
        )
    )
    bars = {
        symbol: load_bars(args.data_dir, symbol, config.bar_size)
        for symbol in loaded_symbols
    }
    if args.chronological_split:
        if args.start_date is not None or args.end_date is not None:
            parser.error("--chronological-split cannot be combined with date bounds")
        payload = {
            name: _result_payload(result)
            for name, result in evaluate_chronological_splits(bars, config).items()
        }
        if not args.include_trades:
            for item in payload.values():
                item.pop("trades", None)
    else:
        result = run_orb_research_backtest(
            bars, config, start_date=args.start_date, end_date=args.end_date
        )
        payload = _result_payload(result)
        if not args.include_trades:
            payload.pop("trades", None)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
