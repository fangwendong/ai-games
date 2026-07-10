from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from ibkr_quant_bot.broker import BrokerError
from ibkr_quant_bot.cli import NEW_YORK, _fresh_historical_bars, _strategy_quote
from ibkr_quant_bot.config import Settings
from ibkr_quant_bot.models import Bar, Quote


class FakeBroker:
    def __init__(self, bars: list[Bar] | None = None):
        self.bars = bars or []
        self.live_quote_called = False
        self.quote_called = False

    def historical_bars(self, symbol: str, duration: str = "1 D", bar_size: str = "1 min", what_to_show: str = "TRADES") -> list[Bar]:
        return self.bars

    def live_quote(self, symbol: str) -> Quote:
        self.live_quote_called = True
        return Quote(symbol=symbol, bid=10.0, ask=10.1, last=10.05, close=10.0)

    def quote(self, symbol: str) -> Quote:
        self.quote_called = True
        return Quote(symbol=symbol, bid=None, ask=None, last=9.9, close=9.8)


def make_bar(age: timedelta) -> Bar:
    timestamp = datetime.now(NEW_YORK) - age
    return Bar(time=timestamp, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class LiveDataGuardsTest(unittest.TestCase):
    def test_live_strategy_rejects_stale_bars(self) -> None:
        settings = Settings(trading_mode="live", live_bar_max_age_seconds=420)
        broker = FakeBroker([make_bar(timedelta(minutes=20))])

        with self.assertRaisesRegex(BrokerError, "stale"):
            _fresh_historical_bars(broker, settings, "SOXL", bar_size="5 mins")

    def test_live_strategy_accepts_recent_bars(self) -> None:
        settings = Settings(trading_mode="live", live_bar_max_age_seconds=420)
        broker = FakeBroker([make_bar(timedelta(minutes=3))])

        bars = _fresh_historical_bars(broker, settings, "SOXL", bar_size="5 mins")

        self.assertEqual(1, len(bars))

    def test_live_strategy_forces_live_quote(self) -> None:
        settings = Settings(trading_mode="live")
        broker = FakeBroker()

        quote = _strategy_quote(broker, settings, "SOXL")

        self.assertTrue(broker.live_quote_called)
        self.assertFalse(broker.quote_called)
        self.assertEqual(10.05, quote.last)

    def test_broker_live_quote_rejects_close_only_quote(self) -> None:
        from ibkr_quant_bot.broker import IbkrBroker

        broker = object.__new__(IbkrBroker)
        broker._quote_with_type = lambda symbol, market_data_type: Quote(  # type: ignore[attr-defined]
            symbol=symbol,
            bid=None,
            ask=None,
            last=None,
            close=10.0,
        )

        with self.assertRaisesRegex(BrokerError, "live quote unavailable"):
            broker.live_quote("SOXL")


if __name__ == "__main__":
    unittest.main()
