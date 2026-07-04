from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar, Strategy


@dataclass(frozen=True)
class VolatilityManagedTrendStrategy(Strategy):
    trend_window: int = 60
    volatility_window: int = 20
    max_annualized_volatility: float = 0.20
    quantity: int = 1
    name: str = "volatility_managed_trend"

    def generate(
        self,
        symbol: str,
        bars: list[Bar],
        position: PositionSnapshot | None = None,
    ) -> OrderIntent | None:
        required_bars = max(self.trend_window, self.volatility_window) + 1
        if len(bars) < required_bars:
            return None

        closes = [bar.close for bar in bars]
        trend_mean = mean(closes[-self.trend_window :])
        last_close = closes[-1]
        realized_volatility = _annualized_volatility(closes[-(self.volatility_window + 1) :])

        long_exposure = last_close >= trend_mean and realized_volatility <= self.max_annualized_volatility
        current_qty = max(1, int(abs(position.quantity))) if position and position.quantity else 0

        if long_exposure:
            if current_qty > 0:
                return None
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.BUY,
                quantity=self.quantity,
                limit_price=round(last_close * 0.999, 2),
                reason=(
                    f"{self.name}: trend up and vol {realized_volatility:.3f} "
                    f"within cap {self.max_annualized_volatility:.3f}"
                ),
            )

        if current_qty > 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.SELL,
                quantity=current_qty,
                limit_price=round(last_close * 1.001, 2),
                reason=(
                    f"{self.name}: trend down or vol {realized_volatility:.3f} "
                    f"above cap {self.max_annualized_volatility:.3f}"
                ),
            )

        return None


def _annualized_volatility(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    returns = [(current / previous) - 1.0 for previous, current in zip(closes, closes[1:])]
    if len(returns) < 2:
        return abs(returns[0]) * sqrt(252)
    return pstdev(returns) * sqrt(252)
