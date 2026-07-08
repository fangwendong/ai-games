from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ibkr_bot.models import OrderIntent, PositionSnapshot, Side
from ibkr_bot.strategy.base import Bar, Strategy


@dataclass(frozen=True)
class VwapPullbackCandidate:
    symbol: str
    score: float
    signal: str
    vwap: float
    current_close: float
    pullback_depth: float
    volume_multiple: float


@dataclass(frozen=True)
class VwapPullbackStrategy(Strategy):
    pullback_window: int = 12
    trend_window: int = 16
    volume_window: int = 4
    pullback_depth: float = 0.0075
    min_volume_multiple: float = 1.0
    min_trend_return: float = 0.003
    switch_score_margin: float = 0.05
    entry_requires_cross: bool = True
    stop_loss_pct: float = 0.015
    max_hold_bars: int = 36
    flat_at_session_end: bool = True
    quantity: int = 1
    name: str = "vwap_pullback"

    def score(self, symbol: str, bars: list[Bar]) -> VwapPullbackCandidate | None:
        session = _session_bars(bars)
        required_bars = max(self.pullback_window + 1, self.volume_window + 1, self.trend_window + 1)
        if len(session) < required_bars:
            return None

        current_close = session[-1].close
        vwap = _session_vwap(session)
        recent_closes = [bar.close for bar in session[-self.pullback_window :]]
        recent_low = min(recent_closes)
        volume_multiple = _volume_multiple(session[-self.volume_window :])
        trend_closes = [bar.close for bar in session[-(self.trend_window + 1) :]]
        trend_return = trend_closes[-1] / trend_closes[0] - 1.0
        pullback_strength = max(0.0, (vwap - recent_low) / vwap) if vwap > 0 else 0.0
        previous_close = session[-2].close
        signal = "NONE"
        score = 0.0

        reclaim_cross = previous_close <= vwap < current_close
        breakdown_cross = previous_close >= vwap > current_close
        reclaim = (
            current_close > vwap
            and recent_low <= vwap * (1.0 - self.pullback_depth)
            and trend_return >= self.min_trend_return
            and current_close >= trend_closes[-1]
        )
        if self.entry_requires_cross:
            reclaim = reclaim and reclaim_cross

        breakdown = current_close < vwap
        if self.entry_requires_cross:
            breakdown = breakdown and breakdown_cross

        if reclaim and volume_multiple >= self.min_volume_multiple:
            signal = "BUY"
            score = (
                pullback_strength
                + 0.75 * trend_return
                + 0.02 * (volume_multiple - 1.0)
            )
        elif breakdown:
            signal = "SELL"
            score = (current_close / vwap) - 1.0 - 0.02 * (volume_multiple - 1.0)

        return VwapPullbackCandidate(
            symbol=symbol,
            score=score,
            signal=signal,
            vwap=vwap,
            current_close=current_close,
            pullback_depth=self.pullback_depth,
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
                    f"{self.name}: reclaimed VWAP {candidate.vwap:.2f} "
                    f"after pullback, trend ok, vol x{candidate.volume_multiple:.2f}"
                ),
            )

        if candidate.signal == "SELL" and current_qty > 0:
            return OrderIntent.limit(
                symbol=symbol,
                side=Side.SELL,
                quantity=current_qty,
                limit_price=round(last_close * 1.001, 2),
                reason=f"{self.name}: lost VWAP {candidate.vwap:.2f}",
            )

        return None


def _session_bars(bars: list[Bar]) -> list[Bar]:
    if not bars:
        return []
    session_date = _parse_intraday_timestamp(bars[-1].timestamp).date()
    return [bar for bar in bars if _parse_intraday_timestamp(bar.timestamp).date() == session_date]


def _session_vwap(bars: list[Bar]) -> float:
    total_notional = 0.0
    total_volume = 0.0
    for bar in bars:
        volume = float(bar.volume or 0.0)
        if volume <= 0:
            volume = 1.0
        total_notional += bar.close * volume
        total_volume += volume
    return total_notional / total_volume if total_volume > 0 else bars[-1].close


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
