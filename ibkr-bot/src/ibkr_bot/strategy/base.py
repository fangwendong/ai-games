from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ibkr_bot.models import OrderIntent


@dataclass(frozen=True)
class Bar:
    timestamp: str
    close: float


class Strategy(ABC):
    name: str

    @abstractmethod
    def generate(self, symbol: str, bars: list[Bar]) -> OrderIntent | None:
        """Return one intended order or None when no trade is needed."""

