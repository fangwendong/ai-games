from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log10, sqrt
from statistics import pstdev

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar


DEFAULT_ETF_CATALOG: tuple[str, ...] = (
    "SPY",
    "VOO",
    "IVV",
    "VTI",
    "QQQ",
    "DIA",
    "IWM",
    "SCHD",
    "VIG",
    "DGRO",
    "QUAL",
    "USMV",
    "SPLV",
    "XLK",
    "XLF",
    "XLV",
    "XLY",
    "XLP",
    "XLE",
    "XLI",
    "XLB",
    "XLRE",
    "XLC",
    "TLT",
    "IEF",
    "SHY",
    "GLD",
)


@dataclass(frozen=True)
class RotationCandidate:
    symbol: str
    score: float
    trailing_return: float
    annualized_volatility: float
    max_drawdown: float
    consistency: float
    average_volume: float


@dataclass(frozen=True)
class RotationPlan:
    selected_symbol: str | None
    candidates: tuple[RotationCandidate, ...]
    orders: tuple[OrderIntent, ...]


@dataclass(frozen=True)
class QualityLowVolRotationStrategy:
    lookback: int = 60
    volatility_window: int = 20
    volume_window: int = 20
    max_annualized_volatility: float = 0.20
    min_average_volume: float = 1_000_000.0
    min_score: float = -10.0
    quantity: int = 1
    name: str = "quality_low_vol_rotation"

    def build_plan(
        self,
        universe: dict[str, list[Bar]],
        positions: dict[str, PositionSnapshot],
    ) -> RotationPlan:
        candidates = [
            candidate
            for symbol, bars in universe.items()
            if (candidate := self.score(symbol, bars)) is not None
            and candidate.annualized_volatility <= self.max_annualized_volatility
        ]
        candidates.sort(
            key=lambda candidate: (
                candidate.score,
                candidate.trailing_return,
                -candidate.annualized_volatility,
                -candidate.max_drawdown,
            ),
            reverse=True,
        )

        selected_symbol = candidates[0].symbol if candidates and candidates[0].score >= self.min_score else None
        orders: list[OrderIntent] = []
        current_positions = {symbol: position for symbol, position in positions.items() if position.quantity > 0}

        if selected_symbol is None:
            for symbol, position in current_positions.items():
                orders.append(
                    OrderIntent.limit(
                        symbol=symbol,
                        side=Side.SELL,
                        quantity=max(1, ceil(abs(position.quantity))),
                        limit_price=max(0.01, round(position.market_price * 0.999, 2)),
                        reason=f"{self.name}: no candidate cleared the score threshold",
                    )
                )
            return RotationPlan(selected_symbol=None, candidates=tuple(candidates), orders=tuple(orders))

        for symbol, position in current_positions.items():
            if symbol == selected_symbol:
                continue
            orders.append(
                OrderIntent.limit(
                    symbol=symbol,
                    side=Side.SELL,
                    quantity=max(1, ceil(abs(position.quantity))),
                    limit_price=max(0.01, round(position.market_price * 0.999, 2)),
                    reason=f"{self.name}: rotated into {selected_symbol}",
                )
            )

        if selected_symbol not in current_positions:
            last_close = _last_close(universe[selected_symbol])
            orders.append(
                OrderIntent.limit(
                    symbol=selected_symbol,
                    side=Side.BUY,
                    quantity=self.quantity,
                    limit_price=max(0.01, round(last_close * 0.999, 2)),
                    reason=f"{self.name}: selected top-ranked candidate",
                )
            )

        return RotationPlan(selected_symbol=selected_symbol, candidates=tuple(candidates), orders=tuple(orders))

    def score(self, symbol: str, bars: list[Bar]) -> RotationCandidate | None:
        if len(bars) < max(self.lookback, self.volume_window) + 1:
            return None

        trailing_bars = bars[-(self.lookback + 1) :]
        closes = [bar.close for bar in trailing_bars]
        trailing_return = closes[-1] / closes[0] - 1.0
        annualized_volatility = _annualized_volatility(closes[-(self.volatility_window + 1) :])
        max_drawdown = _max_drawdown(closes)
        consistency = _positive_return_ratio(closes)
        average_volume = _average_volume(trailing_bars[-self.volume_window :])

        if average_volume < self.min_average_volume:
            return None

        score = (
            1.5 * trailing_return
            + 0.75 * consistency
            - 1.0 * annualized_volatility
            - 0.75 * max_drawdown
            + 0.05 * log10(average_volume)
        )
        return RotationCandidate(
            symbol=symbol,
            score=score,
            trailing_return=trailing_return,
            annualized_volatility=annualized_volatility,
            max_drawdown=max_drawdown,
            consistency=consistency,
            average_volume=average_volume,
        )


def _annualized_volatility(closes: list[float]) -> float:
    returns = [(current / previous) - 1.0 for previous, current in zip(closes, closes[1:])]
    if len(returns) < 2:
        return 0.0
    return pstdev(returns) * sqrt(252)


def _max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    max_drawdown = 0.0
    for close in closes[1:]:
        peak = max(peak, close)
        if peak <= 0:
            continue
        drawdown = (peak - close) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def _positive_return_ratio(closes: list[float]) -> float:
    returns = [(current / previous) - 1.0 for previous, current in zip(closes, closes[1:])]
    if not returns:
        return 0.0
    positives = sum(1 for value in returns if value > 0)
    return positives / len(returns)


def _average_volume(bars: list[Bar]) -> float:
    volumes = [bar.volume for bar in bars if bar.volume is not None and bar.volume > 0]
    if not volumes:
        return 0.0
    return sum(volumes) / len(volumes)


def _last_close(bars: list[Bar]) -> float:
    return bars[-1].close if bars else 0.0
