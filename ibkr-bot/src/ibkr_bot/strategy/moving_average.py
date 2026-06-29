from __future__ import annotations

from dataclasses import dataclass

from ibkr_bot.models import OrderIntent, Side
from ibkr_bot.strategy.base import Bar, Strategy


@dataclass(frozen=True)
class MovingAverageCrossStrategy(Strategy):
    fast_window: int = 5
    slow_window: int = 20
    quantity: int = 1
    name: str = "moving_average_cross"

    def generate(self, symbol: str, bars: list[Bar]) -> OrderIntent | None:
        if len(bars) < self.slow_window + 1:
            return None

        closes = [bar.close for bar in bars]
        previous_fast = _mean(closes[-self.fast_window - 1 : -1])
        previous_slow = _mean(closes[-self.slow_window - 1 : -1])
        current_fast = _mean(closes[-self.fast_window :])
        current_slow = _mean(closes[-self.slow_window :])
        last_price = closes[-1]

        if previous_fast <= previous_slow and current_fast > current_slow:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.BUY,
                quantity=self.quantity,
                limit_price=round(last_price * 0.999, 2),
                reason=f"{self.name}: fast MA crossed above slow MA",
            )

        if previous_fast >= previous_slow and current_fast < current_slow:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.SELL,
                quantity=self.quantity,
                limit_price=round(last_price * 1.001, 2),
                reason=f"{self.name}: fast MA crossed below slow MA",
            )

        return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)

