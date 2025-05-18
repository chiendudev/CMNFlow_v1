from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict

from aiohttp import ClientSession
from typing import List
from src.core.settings import Settings
from src.data.kline import Kline
from src.data.trade import Trade, TradeSummary
from trading.enums import KlineIntervals

class IExchange(ABC):
    @abstractmethod
    async def fetch_klines(self, symbol: str, interval: KlineIntervals, start_time: str, end_time: str) -> List[Kline]:
        pass

    @abstractmethod
    async def fetch_trades(self, symbol: str, start_time: int, end_time: int) -> List[TradeSummary]:
        pass

class ExchangeClient(IExchange):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://fapi.binance.com"

    async def fetch_klines(self, symbol: str, interval: KlineIntervals, start_time: str, end_time: str) -> List[Kline]:
        async with ClientSession() as session:
            params = {
                "symbol": symbol,
                "interval": interval.value,
                "startTime": int(datetime.strptime(start_time, "%d/%m/%Y").timestamp() * 1000),
                "endTime": int(datetime.strptime(end_time, "%d/%m/%Y").timestamp() * 1000),
                "limit": 1000
            }
            async with session.get(f"{self.base_url}/fapi/v1/klines", params=params) as resp:
                data = await resp.json()
                return [Kline(
                    symbol=symbol,
                    timeframe=interval.value,
                    open_time=int(item[0]),
                    close_time=int(item[6]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    num_trades=int(item[8])
                ) for item in data]

    async def fetch_trades(self, symbol: str, start_time: int, end_time: int) -> List[TradeSummary]:
        async with ClientSession() as session:
            params = {"symbol": symbol, "fromId": 0, "limit": 1000}
            async with session.get(f"{self.base_url}/fapi/v1/aggTrades", params=params) as resp:
                data = await resp.json()
                trades = [Trade.model_validate(item) for item in data]
                summaries: Dict[float, TradeSummary] = {}
                for trade in trades:
                    if start_time <= trade.timestamp <= end_time:
                        if trade.price not in summaries:
                            summaries[trade.price] = TradeSummary(price=trade.price, last_update=trade.timestamp)
                        summaries[trade.price].update(trade)
                return list(summaries.values())