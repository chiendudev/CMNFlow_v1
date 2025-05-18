from typing import List
from pydantic import BaseModel, Field
from .trade import TradeSummary

class Kline(BaseModel):
    symbol: str
    timeframe: str
    open_time: int
    close_time: int
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    num_trades: int = 0
    trades: List[TradeSummary] = Field(default_factory=list)
    is_closed: bool = False

    def update(self, price: float, qty: float, num_trades: int) -> None:
        self.high = max(self.high, price) if self.high else price
        self.low = min(self.low, price) if self.low else price
        self.close = price
        self.volume += qty
        self.num_trades += num_trades
