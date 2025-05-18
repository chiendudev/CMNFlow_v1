import aiohttp
from typing import List, Dict, Any
from old.config.settings import Settings
import logging
from asyncio_throttle import Throttler
from collections import deque

logger = logging.getLogger(__name__)

class BinanceRestClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.rest_api_url
        self.throttler = Throttler(rate_limit=100, period=60)  # 100 request/phút

    async def fetch_historical_klines(self, symbol: str, interval: str, limit: int = 1000) -> List[Dict[str, Any]]:
        endpoint = "/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        async with self.throttler:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(f"{self.base_url}{endpoint}", params=params) as response:
                        if response.status == 200:
                            klines = await response.json()
                            return [{
                                "open_time": kline[0],
                                "open": float(kline[1]),
                                "high": float(kline[2]),
                                "low": float(kline[3]),
                                "close": float(kline[4]),
                                "volume": float(kline[5]),
                                "close_time": kline[6],
                                "trades": int(kline[8])
                            } for kline in klines]
                        else:
                            logger.error("Lỗi khi lấy kline lịch sử cho %s, interval %s: %s", symbol, interval, response.status)
                            return []
                except Exception as e:
                    logger.error("Lỗi khi gọi REST API: %s", e)
                    return []

    async def initialize_historical_data(self, symbol: str, storage) -> None:
        # Lấy kline cho tất cả timeframes (bao gồm 1m, 5m, 15m và historical_intervals)
        for interval in self.settings.timeframes + self.settings.historical_intervals:
            # Giới hạn số lượng kline cho timeframe nhỏ để tránh vượt quota
            limit = 100 if interval in self.settings.timeframes else 1000
            klines = await self.fetch_historical_klines(symbol, interval, limit=limit)
            if klines:
                logger.info("Đã lấy %d kline lịch sử cho %s, interval %s", len(klines), symbol, interval)
                for kline_data in klines:
                    from old.data.kline import Kline
                    kline = Kline(
                        open_time=kline_data["open_time"],
                        open_price=kline_data["open"],
                        close_time=kline_data["close_time"],
                        settings=self.settings,
                        symbol=symbol
                    )
                    kline.high = kline_data["high"]
                    kline.low = kline_data["low"]
                    kline.close = kline_data["close"]
                    kline.volume = kline_data["volume"]
                    kline.trades = kline_data["trades"]
                    kline.technical.calculate()
                    if interval not in storage.kline_data[symbol]:
                        storage.kline_data[symbol][interval] = deque(maxlen=self.settings.max_klines)
                    storage.kline_data[symbol][interval].append(kline)
                storage.save(symbol, interval)