
from typing import Callable, Dict, List
from dataclasses import dataclass

@dataclass
class TradeEvent:
    symbol: str
    data: dict

@dataclass
class SignalEvent:
    symbol: str
    timeframe: str
    signal: dict

class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def subscribe(self, even_type: str, handler: Callable) -> None:
        if even_type not in self._handlers:
            self._handlers[even_type] = []
        self._handlers[even_type].append(handler)

    async def publish(self, even_type: str, event: object) -> None:
        if even_type in self._handlers:
            for handler in self._handlers[even_type]:
                await handler(event)