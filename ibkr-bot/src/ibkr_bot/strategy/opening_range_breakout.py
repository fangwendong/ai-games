from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar, Strategy


@dataclass(frozen=True)
class OpeningRangeBreakoutCandidate:
    symbol: str
    score: float
    signal: str
    opening_range_high: float
    opening_range_low: float
    current_close: float
    breakout_gap: float
    volume_multiple: float


@dataclass(frozen=True)
class OpeningRangeBreakoutStrategy(Strategy):
    opening_range_bars: int = 6
    volume_window: int = 4
    min_breakout_gap: float = 0.001
    min_volume_multiple: float = 1.1
    switch_score_margin: float = 0.01
    quantity: int = 1
    name: str = "opening_range_breakout"

    def score(self, symbol: str, bars: list[Bar]) -> OpeningRangeBreakoutCandidate | None:
        session = _session_bars(bars)
        required_bars = max(self.opening_range_bars + 1, self.volume_window + 1)
        if len(session) < required_bars:
            return None

        opening_bars = session[: self.opening_range_bars]
        current_close = session[-1].close
        opening_range_high = max(bar.close for bar in opening_bars)
        opening_range_low = min(bar.close for bar in opening_bars)
        volume_multiple = _volume_multiple(session[-self.volume_window :])
        breakout_gap = 0.0
        signal = "NONE"

        if opening_range_high > 0:
            breakout_gap = (current_close / opening_range_high) - 1.0
        breakdown_gap = 0.0
        if opening_range_low > 0:
            breakdown_gap = (current_close / opening_range_low) - 1.0

        if (
            current_close > opening_range_high * (1.0 + self.min_breakout_gap)
            and volume_multiple >= self.min_volume_multiple
        ):
            signal = "BUY"
        elif current_close < opening_range_low * (1.0 - self.min_breakout_gap):
            signal = "SELL"

        score = breakout_gap + 0.01 * (volume_multiple - 1.0)
        if signal == "SELL":
            score = breakdown_gap - 0.01 * (volume_multiple - 1.0)

        return OpeningRangeBreakoutCandidate(
            symbol=symbol,
            score=score,
            signal=signal,
            opening_range_high=opening_range_high,
            opening_range_low=opening_range_low,
            current_close=current_close,
            breakout_gap=breakout_gap,
            volume_multiple=volume_multiple,
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

        current_qty = max(1, int(abs(position.quantity))) if position and position.quantity else 0
        last_close = bars[-1].close if bars else 0.0

        if candidate.signal == "BUY" and current_qty == 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.BUY,
                quantity=self.quantity,
                limit_price=round(last_close * 0.999, 2),
                reason=(
                    f"{self.name}: breakout above opening range high "
                    f"{candidate.opening_range_high:.2f}, vol x{candidate.volume_multiple:.2f}"
                ),
            )

        if candidate.signal == "SELL" and current_qty > 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.SELL,
                quantity=current_qty,
                limit_price=round(last_close * 1.001, 2),
                reason=(
                    f"{self.name}: broke below opening range low "
                    f"{candidate.opening_range_low:.2f}"
                ),
            )

        return None


def _session_bars(bars: list[Bar]) -> list[Bar]:
    if not bars:
        return []
    session_date = _parse_intraday_timestamp(bars[-1].timestamp).date()
    return [bar for bar in bars if _parse_intraday_timestamp(bar.timestamp).date() == session_date]


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
