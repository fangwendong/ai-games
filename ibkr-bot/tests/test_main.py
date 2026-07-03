from ibkr_bot.main import _format_quote, _resolve_symbol, _resolve_symbol_list
from ibkr_bot.models import QuoteSnapshot


def test_resolve_symbol_prefers_override() -> None:
    assert _resolve_symbol(("SPY", "QQQ"), "aapl") == "AAPL"


def test_resolve_symbol_falls_back_to_first_default() -> None:
    assert _resolve_symbol(("SPY", "QQQ"), None) == "SPY"


def test_resolve_symbol_list_uses_overrides() -> None:
    assert _resolve_symbol_list(("SPY", "QQQ"), ["aapl", " msft "]) == ["AAPL", "MSFT"]


def test_format_quote_includes_core_fields() -> None:
    quote = QuoteSnapshot(
        symbol="SPY",
        source="live",
        bid=499.12,
        ask=499.18,
        last=499.15,
        close=498.5,
        market_price=499.14,
        volume=123456,
        timestamp="2026-07-04 10:15:00",
    )

    text = _format_quote(quote)

    assert "SPY: quote source=live" in text
    assert "bid=499.12" in text
    assert "ask=499.18" in text
    assert "market=499.14" in text
    assert "volume=123456" in text
    assert "time=2026-07-04 10:15:00" in text
