from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from statistics import fmean
from zoneinfo import ZoneInfo

from .models import Bar, Quote, StrategyDecision


NEW_YORK = ZoneInfo("America/New_York")


def _sma(values: list[float], window: int) -> float:
    if not values:
        raise ValueError("no values provided")
    window = max(1, min(window, len(values)))
    return fmean(values[-window:])


def _ema_series(values: list[float], window: int) -> list[float]:
    if not values:
        raise ValueError("no values provided")
    window = max(1, min(window, len(values)))
    alpha = 2 / (window + 1)
    ema = values[0]
    series: list[float] = []
    for value in values:
        ema = alpha * value + (1 - alpha) * ema
        series.append(ema)
    return series


def _vwap_series(bars: list[Bar]) -> list[float]:
    series: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        cum_pv += typical * bar.volume
        cum_v += bar.volume
        series.append(cum_pv / cum_v if cum_v > 0 else bar.close)
    return series


def _atr(bars: list[Bar], window: int) -> float:
    if not bars:
        return 0.0
    true_ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        true_range = bar.high - bar.low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        true_ranges.append(max(0.0, true_range))
        previous_close = bar.close
    return _sma(true_ranges, window)


@dataclass(frozen=True)
class MovingAverageStrategy:
    fast: int = 5
    slow: int = 20
    quantity: int = 1

    def decide(self, symbol: str, quote: Quote, bars: list[Bar]) -> StrategyDecision:
        closes = [bar.close for bar in bars]
        if len(closes) < self.slow:
            return StrategyDecision(
                symbol=symbol.upper(),
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=f"need at least {self.slow} bars",
                signal=False,
                meta={"bars": len(closes)},
            )

        fast_sma = _sma(closes, self.fast)
        slow_sma = _sma(closes, self.slow)
        latest = closes[-1]
        bullish = fast_sma > slow_sma and latest >= fast_sma
        action = "BUY" if bullish else "HOLD"
        return StrategyDecision(
            symbol=symbol.upper(),
            action=action,
            quantity=self.quantity if bullish else 0,
            reference_price=quote.reference_price,
            limit_price=None,
            reason=f"fast={fast_sma:.2f} slow={slow_sma:.2f} latest={latest:.2f}",
            signal=bullish,
            meta={
                "fast": fast_sma,
                "slow": slow_sma,
                "latest": latest,
                "bars": len(closes),
            },
        )


@dataclass(frozen=True)
class VwapPullbackStrategy:
    symbols: tuple[str, ...] = ("SOXL", "TQQQ", "TECL")
    max_notional: float = 1_000.0
    opening_range_bars: int = 15
    touch_lookback: int = 5
    min_bars: int = 15

    def _vwap_series(self, bars: list[Bar]) -> list[float]:
        series: list[float] = []
        cum_pv = 0.0
        cum_v = 0.0
        for bar in bars:
            typical = (bar.high + bar.low + bar.close) / 3.0
            cum_pv += typical * bar.volume
            cum_v += bar.volume
            if cum_v <= 0:
                series.append(0.0)
            else:
                series.append(cum_pv / cum_v)
        return series

    def decide(self, symbol: str, quote: Quote, bars: list[Bar]) -> StrategyDecision:
        symbol = symbol.upper()
        if len(bars) < self.min_bars:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=f"need at least {self.min_bars} bars",
                signal=False,
                meta={"bars": len(bars)},
            )

        vwap_series = self._vwap_series(bars)
        last = bars[-1]
        prev = bars[-2]
        last_vwap = vwap_series[-1]
        or_window = bars[: min(self.opening_range_bars, len(bars))]
        or_high = max(bar.high for bar in or_window)
        or_low = min(bar.low for bar in or_window)
        lookback_bars = bars[-min(self.touch_lookback, len(bars)) :]
        lookback_vwaps = vwap_series[-len(lookback_bars) :]

        touched = any(
            bar.low <= vwap for bar, vwap in zip(lookback_bars, lookback_vwaps)
        )
        reclaimed = last.close > last_vwap and last.close >= prev.close
        breakout = last.close > or_high
        signal = touched and reclaimed and breakout and last.close >= prev.high

        reference_price = quote.ask or quote.last or quote.close or last.close
        limit_price = round(max(reference_price, last.close), 2)
        quantity = int(self.max_notional // limit_price) if limit_price > 0 else 0
        if not signal or quantity <= 0:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=reference_price,
                limit_price=None,
                reason=(
                    f"close={last.close:.2f} vwap={last_vwap:.2f} or_high={or_high:.2f} "
                    f"touched={touched} reclaimed={reclaimed} breakout={breakout}"
                ),
                signal=False,
                meta={
                    "close": last.close,
                    "vwap": last_vwap,
                    "or_high": or_high,
                    "or_low": or_low,
                    "touched": touched,
                    "reclaimed": reclaimed,
                    "breakout": breakout,
                    "quantity": quantity,
                    "bars": len(bars),
                },
            )

        return StrategyDecision(
            symbol=symbol,
            action="BUY",
            quantity=quantity,
            reference_price=reference_price,
            limit_price=limit_price,
            reason=(
                f"close={last.close:.2f} vwap={last_vwap:.2f} or_high={or_high:.2f} "
                f"touched={touched} reclaimed={reclaimed} breakout={breakout}"
            ),
            signal=True,
            meta={
                "close": last.close,
                "vwap": last_vwap,
                "or_high": or_high,
                "or_low": or_low,
                "touched": touched,
                "reclaimed": reclaimed,
                "breakout": breakout,
                "bars": len(bars),
            },
        )


@dataclass(frozen=True)
class IntradayMomentumStrategy:
    symbols: tuple[str, ...] = ("SOXL", "TQQQ", "TECL")
    max_notional: float = 1_000.0
    benchmark_symbol: str = "QQQ"
    benchmark_fast_window: int = 13
    benchmark_slow_window: int = 21
    benchmark_trend_lookback: int = 5
    fast_window: int = 13
    slow_window: int = 21
    trend_window: int = 34
    trend_lookback: int = 5
    min_bars: int = 30
    stop_loss_pct: float = 0.008
    take_profit_pct: float = 0.02
    require_vwap_confirmation: bool = True
    min_confirm_bars: int = 2
    min_trend_gap: float = 0.0015
    min_vwap_gap: float = 0.0005
    min_score: float = 0.008
    require_benchmark_confirmation: bool = True
    max_risk_per_trade: float = 300.0
    atr_window: int = 14
    atr_stop_multiple: float = 2.0
    use_exit_hysteresis: bool = False
    exit_confirm_bars: int = 3
    exit_reversal_votes: int = 2

    def stop_loss_pct_for(self, symbol: str) -> float:
        return self.stop_loss_pct

    def take_profit_pct_for(self, symbol: str) -> float:
        return self.take_profit_pct

    def protective_prices(
        self, symbol: str, average_cost: float, bars: list[Bar]
    ) -> tuple[float, float]:
        atr_distance = _atr(bars, self.atr_window) * self.atr_stop_multiple
        stop_distance = max(average_cost * self.stop_loss_pct_for(symbol), atr_distance)
        return max(0.01, average_cost - stop_distance), average_cost * (
            1 + self.take_profit_pct_for(symbol)
        )

    def _benchmark_bullish(self, bars: list[Bar]) -> bool:
        if len(bars) < max(
            self.benchmark_fast_window,
            self.benchmark_slow_window,
            self.benchmark_trend_lookback,
        ):
            return False
        closes = [bar.close for bar in bars]
        fast_series = _ema_series(closes, self.benchmark_fast_window)
        slow_series = _ema_series(closes, self.benchmark_slow_window)
        fast = fast_series[-1]
        slow = slow_series[-1]
        last = closes[-1]
        trend_index = max(0, len(slow_series) - self.benchmark_trend_lookback)
        trend_slope = (slow_series[-1] - slow_series[trend_index]) / last
        return fast > slow and last > fast and trend_slope > 0

    def _snapshot(self, bars: list[Bar]) -> dict[str, float]:
        closes = [bar.close for bar in bars]
        fast_series = _ema_series(closes, self.fast_window)
        slow_series = _ema_series(closes, self.slow_window)
        trend_series = _ema_series(closes, self.trend_window)
        vwap_series = _vwap_series(bars)
        fast = fast_series[-1]
        slow = slow_series[-1]
        trend = trend_series[-1]
        vwap = vwap_series[-1]
        last = closes[-1]
        trend_index = max(0, len(trend_series) - self.trend_lookback)
        lookback_trend = trend_series[trend_index]
        trend_gap = (fast - slow) / last
        vwap_gap = (last - vwap) / last
        trend_slope = (trend - lookback_trend) / last
        above_vwap_bars = 0
        for close, bar_vwap in zip(reversed(closes), reversed(vwap_series)):
            if close > bar_vwap:
                above_vwap_bars += 1
            else:
                break
        score = trend_gap + vwap_gap + max(0.0, trend_slope)
        return {
            "fast_ema": fast,
            "slow_ema": slow,
            "trend_ema": trend,
            "vwap": vwap,
            "last": last,
            "score": score,
            "trend_gap": trend_gap,
            "vwap_gap": vwap_gap,
            "trend_slope": trend_slope,
            "above_vwap_bars": float(above_vwap_bars),
        }

    def _bullish(
        self, bars: list[Bar], benchmark_bars: list[Bar] | None = None
    ) -> bool:
        snapshot = self._snapshot(bars)
        last = snapshot["last"]
        fast = snapshot["fast_ema"]
        slow = snapshot["slow_ema"]
        trend = snapshot["trend_ema"]
        vwap = snapshot["vwap"]
        trend_gap = snapshot["trend_gap"]
        vwap_gap = snapshot["vwap_gap"]
        trend_slope = snapshot["trend_slope"]
        bullish = (
            fast > slow
            and last >= fast
            and last > trend
            and trend_slope > 0
            and trend_gap >= self.min_trend_gap
        )
        if self.require_vwap_confirmation:
            bullish = (
                bullish
                and last > vwap
                and vwap_gap >= self.min_vwap_gap
                and snapshot["above_vwap_bars"] >= float(self.min_confirm_bars)
            )
        if self.require_benchmark_confirmation:
            bullish = (
                bullish
                and benchmark_bars is not None
                and self._benchmark_bullish(benchmark_bars)
            )
        return bullish

    def _technical_reversal_confirmed(self, bars: list[Bar]) -> bool:
        confirm_bars = max(1, self.exit_confirm_bars)
        required_votes = max(1, min(3, self.exit_reversal_votes))
        if len(bars) < confirm_bars:
            return False
        for end in range(len(bars) - confirm_bars + 1, len(bars) + 1):
            snapshot = self._snapshot(bars[:end])
            reversal_votes = sum(
                (
                    snapshot["fast_ema"] <= snapshot["slow_ema"],
                    snapshot["last"] < snapshot["trend_ema"],
                    snapshot["last"] < snapshot["vwap"],
                )
            )
            if reversal_votes < required_votes:
                return False
        return True

    def decide(
        self,
        symbol: str,
        quote: Quote,
        bars: list[Bar],
        benchmark_bars: list[Bar] | None = None,
    ) -> StrategyDecision:
        symbol = symbol.upper()
        if len(bars) < self.min_bars:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=f"need at least {self.min_bars} bars",
                signal=False,
                meta={
                    "bars": len(bars),
                    **(self._snapshot(bars) if bars else {}),
                },
            )

        snapshot = self._snapshot(bars)
        bullish = self._bullish(bars, benchmark_bars)
        reference_price = quote.ask or quote.last or quote.close or snapshot["last"]
        limit_price = round(max(reference_price, snapshot["last"]), 2)
        quantity = int(self.max_notional // limit_price) if limit_price > 0 else 0
        score = float(snapshot["score"])
        atr = _atr(bars, self.atr_window)
        stop_distance = max(
            reference_price * self.stop_loss_pct, atr * self.atr_stop_multiple
        )
        risk_quantity = (
            int(self.max_risk_per_trade // stop_distance) if stop_distance > 0 else 0
        )
        quantity = min(quantity, risk_quantity)

        if not bullish or quantity <= 0 or score < self.min_score:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=reference_price,
                limit_price=None,
                reason=(
                    f"fast={snapshot['fast_ema']:.2f} slow={snapshot['slow_ema']:.2f} trend={snapshot['trend_ema']:.2f} "
                    f"last={snapshot['last']:.2f} vwap={snapshot['vwap']:.2f} bullish={bullish} score={score:.4f}"
                ),
                signal=False,
                meta={
                    **snapshot,
                    "bullish": bullish,
                    "benchmark_bullish": self._benchmark_bullish(benchmark_bars)
                    if benchmark_bars
                    else False,
                    "atr": atr,
                    "stop_distance": stop_distance,
                    "risk_quantity": risk_quantity,
                    "bars": len(bars),
                },
            )

        return StrategyDecision(
            symbol=symbol,
            action="BUY",
            quantity=quantity,
            reference_price=reference_price,
            limit_price=limit_price,
            reason=(
                f"fast={snapshot['fast_ema']:.2f} slow={snapshot['slow_ema']:.2f} trend={snapshot['trend_ema']:.2f} "
                f"last={snapshot['last']:.2f} vwap={snapshot['vwap']:.2f} bullish={bullish} score={score:.4f}"
            ),
            signal=True,
            meta={
                **snapshot,
                "bullish": bullish,
                "benchmark_bullish": self._benchmark_bullish(benchmark_bars)
                if benchmark_bars
                else False,
                "atr": atr,
                "stop_distance": stop_distance,
                "risk_quantity": risk_quantity,
                "bars": len(bars),
            },
        )

    def exit_decide(
        self,
        symbol: str,
        quote: Quote,
        bars: list[Bar],
        quantity: int,
        average_cost: float,
        benchmark_bars: list[Bar] | None = None,
    ) -> StrategyDecision:
        symbol = symbol.upper()
        if quantity <= 0:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason="no open quantity",
                signal=False,
                meta={"bars": len(bars)},
            )

        if len(bars) < self.min_bars:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=f"need at least {self.min_bars} bars",
                signal=False,
                meta={"bars": len(bars)},
            )

        snapshot = self._snapshot(bars)
        last = snapshot["last"]
        stop_price, take_price = self.protective_prices(symbol, average_cost, bars)
        bearish = (
            self._technical_reversal_confirmed(bars)
            if self.use_exit_hysteresis
            else not self._bullish(bars, benchmark_bars)
        )
        stop_hit = last <= stop_price
        take_hit = last >= take_price

        if not (stop_hit or take_hit or bearish):
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=(
                    f"holding avg_cost={average_cost:.2f} stop={stop_price:.2f} take={take_price:.2f} "
                    f"fast={snapshot['fast_ema']:.2f} slow={snapshot['slow_ema']:.2f} trend={snapshot['trend_ema']:.2f} "
                    f"last={last:.2f} vwap={snapshot['vwap']:.2f}"
                ),
                signal=False,
                meta={
                    **snapshot,
                    "bullish": not bearish,
                    "bars": len(bars),
                    "stop_price": stop_price,
                    "take_price": take_price,
                },
            )

        return StrategyDecision(
            symbol=symbol,
            action="SELL",
            quantity=quantity,
            reference_price=quote.reference_price,
            limit_price=None,
            reason=(
                f"exit avg_cost={average_cost:.2f} stop={stop_price:.2f} take={take_price:.2f} "
                f"fast={snapshot['fast_ema']:.2f} slow={snapshot['slow_ema']:.2f} trend={snapshot['trend_ema']:.2f} "
                f"last={last:.2f} vwap={snapshot['vwap']:.2f} "
                f"stop_hit={stop_hit} take_hit={take_hit} bearish={bearish}"
            ),
            signal=True,
            meta={
                **snapshot,
                "bars": len(bars),
                "stop_price": stop_price,
                "take_price": take_price,
                "stop_hit": stop_hit,
                "take_hit": take_hit,
                "bearish": bearish,
            },
        )


@dataclass
class SemiconductorRotationStrategy:
    symbols: tuple[str, ...] = ("SOXL", "SOXS")
    benchmark_symbol: str = "QQQ"
    max_notional: float = 1_000.0
    long_symbol: str = "SOXL"
    short_symbol: str = "SOXS"
    fast_window: int = 13
    slow_window: int = 21
    trend_window: int = 34
    trend_lookback: int = 5
    benchmark_fast_window: int = 13
    benchmark_slow_window: int = 21
    benchmark_trend_lookback: int = 5
    min_bars: int = 30
    long_stop_loss_pct: float = 0.012
    long_take_profit_pct: float = 0.035
    long_min_confirm_bars: int = 1
    long_min_trend_gap: float = 0.001
    long_min_vwap_gap: float = 0.00025
    long_min_score: float = 0.006
    short_stop_loss_pct: float = 0.012
    short_take_profit_pct: float = 0.035
    short_min_confirm_bars: int = 2
    short_min_trend_gap: float = 0.0015
    short_min_vwap_gap: float = 0.00025
    short_min_score: float = 0.006
    require_vwap_confirmation: bool = True
    require_benchmark_confirmation: bool = True
    max_risk_per_trade: float = 300.0
    atr_window: int = 14
    atr_stop_multiple: float = 2.0
    use_exit_hysteresis: bool = False
    exit_confirm_bars: int = 3
    benchmark_exit_confirm_bars: int = 1
    exit_reversal_votes: int = 2
    profit_lock_activation_pct: float | None = None
    profit_lock_drawdown_pct: float | None = None
    entry_fill_cutoff_et_minutes: int | None = None
    benchmark_min_intraday_range: float = 0.0
    long_strategy: IntradayMomentumStrategy = field(init=False, repr=False)
    short_strategy: IntradayMomentumStrategy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.benchmark_min_intraday_range < 0:
            raise ValueError("benchmark_min_intraday_range must be non-negative")
        self.long_symbol = self.long_symbol.upper()
        self.short_symbol = self.short_symbol.upper()
        self.symbols = (self.long_symbol, self.short_symbol)
        self.long_strategy = IntradayMomentumStrategy(
            symbols=(self.long_symbol,),
            benchmark_symbol=self.benchmark_symbol,
            max_notional=self.max_notional,
            fast_window=self.fast_window,
            slow_window=self.slow_window,
            trend_window=self.trend_window,
            trend_lookback=self.trend_lookback,
            benchmark_fast_window=self.benchmark_fast_window,
            benchmark_slow_window=self.benchmark_slow_window,
            benchmark_trend_lookback=self.benchmark_trend_lookback,
            min_bars=self.min_bars,
            stop_loss_pct=self.long_stop_loss_pct,
            take_profit_pct=self.long_take_profit_pct,
            require_vwap_confirmation=self.require_vwap_confirmation,
            min_confirm_bars=self.long_min_confirm_bars,
            min_trend_gap=self.long_min_trend_gap,
            min_vwap_gap=self.long_min_vwap_gap,
            min_score=self.long_min_score,
            require_benchmark_confirmation=self.require_benchmark_confirmation,
            max_risk_per_trade=self.max_risk_per_trade,
            atr_window=self.atr_window,
            atr_stop_multiple=self.atr_stop_multiple,
            use_exit_hysteresis=self.use_exit_hysteresis,
            exit_confirm_bars=self.exit_confirm_bars,
            exit_reversal_votes=self.exit_reversal_votes,
        )
        self.short_strategy = IntradayMomentumStrategy(
            symbols=(self.short_symbol,),
            benchmark_symbol=self.benchmark_symbol,
            max_notional=self.max_notional,
            fast_window=self.fast_window,
            slow_window=self.slow_window,
            trend_window=self.trend_window,
            trend_lookback=self.trend_lookback,
            benchmark_fast_window=self.benchmark_fast_window,
            benchmark_slow_window=self.benchmark_slow_window,
            benchmark_trend_lookback=self.benchmark_trend_lookback,
            min_bars=self.min_bars,
            stop_loss_pct=self.short_stop_loss_pct,
            take_profit_pct=self.short_take_profit_pct,
            require_vwap_confirmation=self.require_vwap_confirmation,
            min_confirm_bars=self.short_min_confirm_bars,
            min_trend_gap=self.short_min_trend_gap,
            min_vwap_gap=self.short_min_vwap_gap,
            min_score=self.short_min_score,
            require_benchmark_confirmation=False,
            max_risk_per_trade=self.max_risk_per_trade,
            atr_window=self.atr_window,
            atr_stop_multiple=self.atr_stop_multiple,
            use_exit_hysteresis=self.use_exit_hysteresis,
            exit_confirm_bars=self.exit_confirm_bars,
            exit_reversal_votes=self.exit_reversal_votes,
        )

    def _benchmark_bullish(self, bars: list[Bar]) -> bool:
        return self.long_strategy._benchmark_bullish(bars)

    def _diagnostic_snapshot(self, symbol: str, bars: list[Bar]) -> dict[str, float]:
        if not bars:
            return {}
        strategy = (
            self.long_strategy
            if symbol.upper() == self.long_symbol
            else self.short_strategy
        )
        return strategy._snapshot(bars)

    def _entry_fill_cutoff_reached(self, bars: list[Bar]) -> bool:
        cutoff = self.entry_fill_cutoff_et_minutes
        if cutoff is None or not bars:
            return False
        bar_time = bars[-1].time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=NEW_YORK)
        estimated_fill_time = bar_time.astimezone(NEW_YORK) + timedelta(minutes=5)
        fill_minutes = estimated_fill_time.hour * 60 + estimated_fill_time.minute
        return fill_minutes >= cutoff

    def _apply_entry_range_gate(
        self,
        decision: StrategyDecision,
        benchmark_bars: list[Bar],
    ) -> StrategyDecision:
        threshold = self.benchmark_min_intraday_range
        if threshold <= 0:
            return decision
        valid_lows = [bar.low for bar in benchmark_bars if bar.low > 0]
        benchmark_range = (
            max(bar.high for bar in benchmark_bars) / min(valid_lows) - 1.0
            if benchmark_bars and valid_lows
            else 0.0
        )
        meta = {
            **decision.meta,
            "benchmark_intraday_range": benchmark_range,
            "benchmark_min_intraday_range": threshold,
            "benchmark_range_gate_passed": benchmark_range >= threshold,
        }
        if not decision.signal or decision.action != "BUY" or benchmark_range >= threshold:
            return StrategyDecision(
                symbol=decision.symbol,
                action=decision.action,
                quantity=decision.quantity,
                reference_price=decision.reference_price,
                limit_price=decision.limit_price,
                reason=decision.reason,
                signal=decision.signal,
                meta=meta,
            )
        return StrategyDecision(
            symbol=decision.symbol,
            action="HOLD",
            quantity=0,
            reference_price=decision.reference_price,
            limit_price=None,
            reason=(
                f"benchmark intraday range {benchmark_range:.4%} below "
                f"minimum {threshold:.4%}"
            ),
            signal=False,
            meta=meta,
        )

    def stop_loss_pct_for(self, symbol: str) -> float:
        symbol = symbol.upper()
        if symbol == self.long_symbol:
            return self.long_stop_loss_pct
        if symbol == self.short_symbol:
            return self.short_stop_loss_pct
        raise ValueError(f"symbol not traded: {symbol}")

    def take_profit_pct_for(self, symbol: str) -> float:
        symbol = symbol.upper()
        if symbol == self.long_symbol:
            return self.long_take_profit_pct
        if symbol == self.short_symbol:
            return self.short_take_profit_pct
        raise ValueError(f"symbol not traded: {symbol}")

    def protective_prices(
        self, symbol: str, average_cost: float, bars: list[Bar]
    ) -> tuple[float, float]:
        symbol = symbol.upper()
        if symbol == self.long_symbol:
            strategy = self.long_strategy
        elif symbol == self.short_symbol:
            strategy = self.short_strategy
        else:
            raise ValueError(f"symbol not traded: {symbol}")
        return strategy.protective_prices(symbol, average_cost, bars)

    def profit_lock_decide(
        self,
        symbol: str,
        quote: Quote,
        bars_since_entry: list[Bar],
        quantity: int,
        average_cost: float,
    ) -> StrategyDecision:
        activation_pct = self.profit_lock_activation_pct
        drawdown_pct = self.profit_lock_drawdown_pct
        enabled = (
            activation_pct is not None
            and activation_pct > 0
            and drawdown_pct is not None
            and drawdown_pct > 0
        )
        if not enabled or not bars_since_entry:
            return StrategyDecision(
                symbol=symbol.upper(),
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason="profit lock disabled or waiting for completed post-entry bars",
                signal=False,
                meta={"profit_lock_enabled": enabled},
            )

        peak_close = max(average_cost, *(bar.close for bar in bars_since_entry))
        current_close = bars_since_entry[-1].close
        activation_price = average_cost * (1.0 + activation_pct)
        lock_price = peak_close * (1.0 - drawdown_pct)
        activated = peak_close >= activation_price
        lock_hit = activated and current_close <= lock_price
        return StrategyDecision(
            symbol=symbol.upper(),
            action="SELL" if lock_hit else "HOLD",
            quantity=quantity if lock_hit else 0,
            reference_price=quote.reference_price,
            limit_price=None,
            reason=(
                f"profit lock peak_close={peak_close:.4f} current_close={current_close:.4f} "
                f"activation={activation_price:.4f} lock={lock_price:.4f} "
                f"activated={activated} hit={lock_hit}"
            ),
            signal=lock_hit,
            meta={
                "profit_lock_enabled": True,
                "profit_lock_activated": activated,
                "profit_lock_hit": lock_hit,
                "profit_lock_peak_close": peak_close,
                "profit_lock_current_close": current_close,
                "profit_lock_activation_price": activation_price,
                "profit_lock_price": lock_price,
            },
        )

    def _benchmark_reversal_confirmed(
        self, symbol: str, benchmark_bars: list[Bar] | None
    ) -> bool:
        confirm_bars = max(1, self.benchmark_exit_confirm_bars)
        if benchmark_bars is None or len(benchmark_bars) < confirm_bars:
            return False
        for end in range(
            len(benchmark_bars) - confirm_bars + 1, len(benchmark_bars) + 1
        ):
            bullish = self._benchmark_bullish(benchmark_bars[:end])
            reversal = not bullish if symbol == self.long_symbol else bullish
            if not reversal:
                return False
        return True

    def decide(
        self,
        symbol: str,
        quote: Quote,
        bars: list[Bar],
        benchmark_bars: list[Bar] | None = None,
    ) -> StrategyDecision:
        symbol = symbol.upper()
        if len(bars) < self.min_bars:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=f"need at least {self.min_bars} bars",
                signal=False,
                meta={"bars": len(bars), **self._diagnostic_snapshot(symbol, bars)},
            )
        if benchmark_bars is None:
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason="need benchmark bars",
                signal=False,
                meta={"bars": len(bars)},
            )
        if self._entry_fill_cutoff_reached(bars):
            cutoff = self.entry_fill_cutoff_et_minutes
            assert cutoff is not None
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason=(
                    "entry window closed before "
                    f"{cutoff // 60:02d}:{cutoff % 60:02d} America/New_York"
                ),
                signal=False,
                meta={
                    "bars": len(bars),
                    "entry_fill_cutoff_et_minutes": cutoff,
                    "entry_window_closed": True,
                    **self._diagnostic_snapshot(symbol, bars),
                },
            )

        bullish = self._benchmark_bullish(benchmark_bars)
        if symbol == self.long_symbol:
            if bullish:
                return self._apply_entry_range_gate(
                    self.long_strategy.decide(
                        symbol, quote, bars, benchmark_bars=benchmark_bars
                    ),
                    benchmark_bars,
                )
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason="regime bearish",
                signal=False,
                meta={
                    "bars": len(bars),
                    "benchmark_bullish": bullish,
                    **self._diagnostic_snapshot(symbol, bars),
                },
            )
        if symbol == self.short_symbol:
            if not bullish:
                return self._apply_entry_range_gate(
                    self.short_strategy.decide(
                        symbol, quote, bars, benchmark_bars=None
                    ),
                    benchmark_bars,
                )
            return StrategyDecision(
                symbol=symbol,
                action="HOLD",
                quantity=0,
                reference_price=quote.reference_price,
                limit_price=None,
                reason="regime bullish",
                signal=False,
                meta={
                    "bars": len(bars),
                    "benchmark_bullish": bullish,
                    **self._diagnostic_snapshot(symbol, bars),
                },
            )
        return StrategyDecision(
            symbol=symbol,
            action="HOLD",
            quantity=0,
            reference_price=quote.reference_price,
            limit_price=None,
            reason="symbol not traded",
            signal=False,
            meta={
                "bars": len(bars),
                "benchmark_bullish": bullish,
                **self._diagnostic_snapshot(symbol, bars),
            },
        )

    def exit_decide(
        self,
        symbol: str,
        quote: Quote,
        bars: list[Bar],
        quantity: int,
        average_cost: float,
        benchmark_bars: list[Bar] | None = None,
    ) -> StrategyDecision:
        symbol = symbol.upper()
        if symbol == self.long_symbol:
            decision = self.long_strategy.exit_decide(
                symbol,
                quote,
                bars,
                quantity,
                average_cost,
                benchmark_bars=benchmark_bars,
            )
            if not decision.signal and self._benchmark_reversal_confirmed(
                symbol, benchmark_bars
            ):
                return StrategyDecision(
                    symbol=symbol,
                    action="SELL",
                    quantity=quantity,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="exit long execution ETF: benchmark regime turned bearish",
                    signal=True,
                    meta={**decision.meta, "benchmark_bullish": False, "bearish": True},
                )
            return decision
        if symbol == self.short_symbol:
            decision = self.short_strategy.exit_decide(
                symbol, quote, bars, quantity, average_cost, benchmark_bars=None
            )
            if not decision.signal and self._benchmark_reversal_confirmed(
                symbol, benchmark_bars
            ):
                return StrategyDecision(
                    symbol=symbol,
                    action="SELL",
                    quantity=quantity,
                    reference_price=quote.reference_price,
                    limit_price=None,
                    reason="exit inverse execution ETF: benchmark regime turned bullish",
                    signal=True,
                    meta={**decision.meta, "benchmark_bullish": True, "bearish": True},
                )
            return decision
        return StrategyDecision(
            symbol=symbol,
            action="HOLD",
            quantity=0,
            reference_price=quote.reference_price,
            limit_price=None,
            reason="symbol not traded",
            signal=False,
            meta={"bars": len(bars)},
        )
