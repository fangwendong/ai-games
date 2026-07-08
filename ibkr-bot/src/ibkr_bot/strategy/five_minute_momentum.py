from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar, Strategy


@dataclass(frozen=True)
class FiveMinuteMomentumCandidate:
    symbol: str
    score: float
    signal: str
    momentum: float
    volume_multiple: float
    fast_sma: float
    slow_sma: float


@dataclass(frozen=True)
class FiveMinuteMomentumStrategy(Strategy):
    fast_window: int = 3
    slow_window: int = 8
    volume_window: int = 4
    min_momentum: float = 0.0
    min_volume_multiple: float = 1.0
    quantity: int = 1
    name: str = "five_minute_momentum"

    def score(self, symbol: str, bars: list[Bar]) -> FiveMinuteMomentumCandidate | None:
        required_bars = max(self.fast_window, self.slow_window, self.volume_window) + 1
        if len(bars) < required_bars:
            return None

        closes = [bar.close for bar in bars]
        current_close = closes[-1]
        fast_sma = mean(closes[-self.fast_window :])
        slow_sma = mean(closes[-self.slow_window :])
        momentum = current_close / closes[-self.fast_window - 1] - 1.0
        volume_multiple = _volume_multiple(bars[-self.volume_window :])

        signal = "NONE"
        if current_close > fast_sma > slow_sma and momentum >= self.min_momentum and volume_multiple >= self.min_volume_multiple:
            signal = "BUY"
        elif current_close < fast_sma < slow_sma and momentum <= -self.min_momentum and volume_multiple >= self.min_volume_multiple:
            signal = "SELL"

        score = momentum + 0.01 * (volume_multiple - 1.0)
        return FiveMinuteMomentumCandidate(
            symbol=symbol,
            score=score,
            signal=signal,
            momentum=momentum,
            volume_multiple=volume_multiple,
            fast_sma=fast_sma,
            slow_sma=slow_sma,
        )

    def generate(
        self,
        symbol: str,
        bars: list[Bar],
        position: PositionSnapshot | None = None,
    ) -> OrderIntent | None:
        candidate = self.score(symbol, bars)
        if candidate is None:
            return None

        bullish = candidate.signal == "BUY"
        bearish = candidate.signal == "SELL"
        current_qty = max(1, int(abs(position.quantity))) if position and position.quantity else 0

        if bullish and current_qty == 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.BUY,
                quantity=self.quantity,
                limit_price=round(bars[-1].close * 0.999, 2),
                reason=(
                    f"{self.name}: fast SMA above slow SMA, "
                    f"momentum {candidate.momentum:.3%}, volume x{candidate.volume_multiple:.2f}"
                ),
            )

        if bearish and current_qty > 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.SELL,
                quantity=current_qty,
                limit_price=round(bars[-1].close * 1.001, 2),
                reason=(
                    f"{self.name}: fast SMA below slow SMA, "
                    f"momentum {candidate.momentum:.3%}, volume x{candidate.volume_multiple:.2f}"
                ),
            )

        return None


def _volume_multiple(bars: list[Bar]) -> float:
    if len(bars) < 2:
        return 0.0
    current_volume = bars[-1].volume or 0.0
    if current_volume <= 0:
        return 0.0
    prior_volumes = [bar.volume for bar in bars[:-1] if bar.volume is not None and bar.volume > 0]
    if not prior_volumes:
        return 0.0
    average_volume = sum(prior_volumes) / len(prior_volumes)
    if average_volume <= 0:
        return 0.0
    return current_volume / average_volume
