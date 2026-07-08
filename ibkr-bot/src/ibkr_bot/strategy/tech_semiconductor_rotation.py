from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log10, sqrt
from statistics import pstdev

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar
from ibkr_bot.strategy.quality_low_vol_rotation import RotationCandidate, RotationPlan


DEFAULT_TECH_SEMICONDUCTOR_CATALOG: tuple[str, ...] = (
    "QQQ",
    "XLK",
    "IYW",
    "SMH",
    "SOXX",
)


@dataclass(frozen=True)
class TechSemiconductorRotationStrategy:
    lookback: int = 60
    volatility_window: int = 20
    volume_window: int = 20
    max_annualized_volatility: float = 0.35
    min_average_volume: float = 1_000_000.0
    min_trailing_return: float = 0.0
    min_score: float = 0.0
    switch_score_margin: float = 0.03
    market_filter_symbol: str = "SPY"
    market_filter_window: int = 50
    quantity: int = 1
    name: str = "tech_semiconductor_rotation"

    def build_plan(
        self,
        universe: dict[str, list[Bar]],
        positions: dict[str, PositionSnapshot],
    ) -> RotationPlan:
        if not self._market_is_risk_on(universe):
            current_positions = {symbol: position for symbol, position in positions.items() if position.quantity > 0}
            orders = [
                OrderIntent.limit(
                    symbol=symbol,
                    side=Side.SELL,
                    quantity=max(1, ceil(abs(position.quantity))),
                    limit_price=max(0.01, round(position.market_price * 0.999, 2)),
                    reason=f"{self.name}: market filter is off",
                )
                for symbol, position in current_positions.items()
            ]
            return RotationPlan(selected_symbol=None, candidates=(), orders=tuple(orders))

        candidates = [
            candidate
            for symbol, bars in universe.items()
            if (candidate := self.score(symbol, bars)) is not None
            and candidate.annualized_volatility <= self.max_annualized_volatility
            and candidate.trailing_return >= self.min_trailing_return
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

        orders: list[OrderIntent] = []
        current_positions = {symbol: position for symbol, position in positions.items() if position.quantity > 0}
        selected_symbol = self._select_symbol(candidates, current_positions)

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
                    reason=f"{self.name}: selected top-ranked tech/semiconductor candidate",
                )
            )

        return RotationPlan(selected_symbol=selected_symbol, candidates=tuple(candidates), orders=tuple(orders))

    def score(self, symbol: str, bars: list[Bar]) -> RotationCandidate | None:
        required_bars = max(self.lookback, self.volatility_window, self.volume_window) + 1
        if len(bars) < required_bars:
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
            1.8 * trailing_return
            + 0.55 * consistency
            - 1.1 * annualized_volatility
            - 0.70 * max_drawdown
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

    def _market_is_risk_on(self, universe: dict[str, list[Bar]]) -> bool:
        if self.market_filter_window <= 0:
            return True
        bars = universe.get(self.market_filter_symbol)
        if bars is None or len(bars) < self.market_filter_window + 1:
            return True
        trailing_bars = bars[-(self.market_filter_window + 1) :]
        closes = [bar.close for bar in trailing_bars]
        average_close = sum(closes[-self.market_filter_window :]) / self.market_filter_window
        return closes[-1] >= average_close

    def _select_symbol(
        self,
        candidates: list[RotationCandidate],
        current_positions: dict[str, PositionSnapshot],
    ) -> str | None:
        if not candidates or candidates[0].score < self.min_score:
            return None

        current_symbols = set(current_positions)
        if current_symbols and self.switch_score_margin > 0:
            current_candidate = next(
                (candidate for candidate in candidates if candidate.symbol in current_symbols),
                None,
            )
            if current_candidate is not None and current_candidate.score >= candidates[0].score - self.switch_score_margin:
                return current_candidate.symbol

        return candidates[0].symbol


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
