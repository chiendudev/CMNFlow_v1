from typing import Dict, List
from old.indicators.technical import TechnicalIndicators
from old.config.settings import Settings
import logging

logger = logging.getLogger(__name__)

class Kline:
    def __init__(self, open_time: int, open_price: float, close_time: int, settings: Settings, symbol: str):
        self.settings = settings
        self.symbol = symbol
        self.open_time = open_time
        self.open = open_price
        self.high = open_price
        self.low = open_price
        self.close = open_price
        self.volume: float = 0.0
        self.trades: int = 0
        self.close_time = close_time
        self.agg_trades: List[Dict] = []
        self.price_qty: Dict[float, Dict] = {}
        self.recent_trades: List[Dict] = []
        self.technical = TechnicalIndicators(self, settings)
        self.close_history: List[float] = []
        self.high_history: List[float] = []
        self.low_history: List[float] = []

    def update(self, price: float, quantity: float, is_maker: bool, timestamp_ms: int):
        """Cập nhật kline với giao dịch mới."""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += quantity
        self.trades += 1
        self.agg_trades.append({"price": price, "quantity": quantity, "is_maker": is_maker, "timestamp_ms": timestamp_ms})
        self.recent_trades.append({"price": price, "quantity": quantity, "is_maker": is_maker, "timestamp_ms": timestamp_ms})
        current_time = timestamp_ms / 1000
        self.recent_trades = [t for t in self.recent_trades if current_time - t["timestamp_ms"] / 1000 <= self.settings.stop_hunt_window]
        rounded_price = round(price, self.settings.price_precision)
        if rounded_price not in self.price_qty:
            self.price_qty[rounded_price] = {"maker_qty": 0.0, "taker_qty": 0.0, "count": 0}
        self.price_qty[rounded_price]["count"] += 1
        if is_maker:
            self.price_qty[rounded_price]["maker_qty"] += quantity
        else:
            self.price_qty[rounded_price]["taker_qty"] += quantity
        self.technical.calculate()

    def to_dict(self):
        """Chuyển kline thành từ điển."""
        zones, avg_qty, _, poc_price, value_area = self.technical.analyze_zones("unknown")
        return {
            "symbol": self.symbol,
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trades": self.trades,
            "close_time": self.close_time,
            "avg_qty_per_price": avg_qty,
            "significant_price_zones": zones,
            "poc_price": poc_price,
            "value_area": value_area,
            "technical_indicators": {
                "rsi": self.technical.rsi,
                "atr": self.technical.atr,
                "ema_fast": self.technical.ema_fast,
                "ema_slow": self.technical.ema_slow
            }
        }