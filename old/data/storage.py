from typing import List, Dict
from old.config.settings import Settings
from collections import deque
import json
import logging
import time

logger = logging.getLogger(__name__)

class DataStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.kline_data: Dict[str, Dict[str, deque]] = {
            symbol: {tf: deque(maxlen=settings.max_klines) for tf in settings.timeframes + settings.historical_intervals}
            for symbol in settings.symbols
        }
        self.confluence_zones: Dict[str, List[Dict]] = {symbol: [] for symbol in settings.symbols}
        self.stop_hunt_events: Dict[str, List[Dict]] = {symbol: [] for symbol in settings.symbols}
        self.positions_data: Dict[str, List[Dict]] = {symbol: [] for symbol in settings.symbols}
        self.last_save: Dict[str, Dict[str, float]] = {
            symbol: {tf: 0.0 for tf in settings.timeframes + settings.historical_intervals}
            for symbol in settings.symbols
        }

    def save(self, symbol: str, timeframe: str):
        current_time = time.time()
        if current_time - self.last_save[symbol][timeframe] < self.settings.save_interval:
            return
        if self.kline_data[symbol][timeframe]:
            data = [kline.to_dict() for kline in self.kline_data[symbol][timeframe]]
            with open(f"kline_{symbol}_{timeframe}.json", "w") as f:
                json.dump(data, f, indent=2)
            logger.debug("Đã lưu kline %s cho %s vào kline_%s_%s.json", timeframe, symbol, symbol, timeframe)
        if self.confluence_zones[symbol]:
            with open(f"confluence_zones_{symbol}.json", "w") as f:
                json.dump(self.confluence_zones[symbol], f, indent=2)
            logger.debug("Đã lưu confluence zones cho %s vào confluence_zones_%s.json", symbol, symbol)
        if self.stop_hunt_events[symbol]:
            with open(f"stop_hunt_events_{symbol}.json", "w") as f:
                json.dump(self.stop_hunt_events[symbol], f, indent=2)
            logger.debug("Đã lưu stop hunt events cho %s vào stop_hunt_events_%s.json", symbol, symbol)
        if self.positions_data[symbol]:
            with open(f"positions_{symbol}.json", "w") as f:
                json.dump(self.positions_data[symbol], f, indent=2)
            logger.debug("Đã lưu positions cho %s vào positions_%s.json", symbol, symbol)
        self.last_save[symbol][timeframe] = current_time

    async def save_all(self):
        for symbol in self.settings.symbols:
            for timeframe in self.settings.timeframes + self.settings.historical_intervals:
                self.save(symbol, timeframe)