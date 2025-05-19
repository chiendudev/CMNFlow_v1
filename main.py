import asyncio
import logging
import json
import aiohttp
from typing import Dict, Any, List
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, FundingRateEvent, OrderBookEvent
from src.core.storage import Storage
from src.core.logging_config import get_logger, setup_logging
from src.exchange.client import ExchangeClient
from src.trading.portfolio import Portfolio
from src.trading.risk import RiskManager
from src.engine import TradingEngine
from src.strategy.signals import SignalGenerator

logger = get_logger(__name__)

class TradingSystem:
    def __init__(self):
        self.settings = Settings()
        setup_logging(self.settings)
        self.event_bus = EventBus(self.settings)
        self.exchange_client = ExchangeClient(self.settings)
        self.storage = Storage(self.settings, self.event_bus)
        self.portfolio = Portfolio(self.settings, self.exchange_client)
        self.risk_manager = RiskManager(self.settings, self.event_bus, self.portfolio, self.storage)
        self.signal_generator = SignalGenerator(
            self.settings, self.event_bus, self.portfolio, self.storage, self.risk_manager
        )
        self.trading_engine = TradingEngine(
            self.settings, self.event_bus, self.portfolio, self.risk_manager, self.storage
        )
        self.ws_session: aiohttp.ClientSession = None
        logger.info("Initialized TradingSystem with symbols=%s, timeframes=%s",
                    self.settings.symbols, self.settings.timeframes)

    async def initialize(self):
        """Khởi tạo database và kết nối WebSocket."""
        try:
            await self.storage.initialize()
            await self.setup_websocket()
            logger.info("System initialized successfully")
        except Exception as e:
            logger.error("Initialization failed: %s", e)
            raise

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=10))
    async def setup_websocket(self):
        """Thiết lập kết nối WebSocket tới Binance Futures."""
        if self.ws_session is None:
            self.ws_session = aiohttp.ClientSession()
        streams = []
        for symbol in self.settings.symbols:
            symbol_lower = symbol.lower()
            for timeframe in self.settings.timeframes:
                streams.append(f"{symbol_lower}@kline_{timeframe}")
            streams.append(f"{symbol_lower}@fundingRate")
            streams.append(f"{symbol_lower}@depth5@100ms")
        stream_path = "/".join(streams)
        ws_url = f"{self.settings.ws_url}/{stream_path}"
        logger.info("Connecting to WebSocket: %s", ws_url)

        async with self.ws_session.ws_connect(ws_url) as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.handle_websocket_message(json.loads(msg.data))
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("WebSocket closed, reconnecting...")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", msg.data)
                    break

    async def handle_websocket_message(self, message: Dict[str, Any]):
        """Xử lý tin nhắn WebSocket và phát sự kiện."""
        try:
            event_type = message.get("e")
            symbol = message.get("s")
            timestamp = message.get("E", int(datetime.now().timestamp() * 1000))

            if event_type == "kline":
                kline_data = message["k"]
                event = KlineEvent(
                    type="kline",
                    symbol=symbol,
                    timeframe=kline_data["i"],
                    open_time=kline_data["t"],
                    close_time=kline_data["T"],
                    open=float(kline_data["o"]),
                    high=float(kline_data["h"]),
                    low=float(kline_data["l"]),
                    close=float(kline_data["c"]),
                    volume=float(kline_data["v"]),
                    num_trades=kline_data["n"],
                    is_closed=kline_data["x"],
                    timestamp=timestamp,
                    data={}
                )
                await self.storage.save_kline(event)
                await self.event_bus.publish("kline", event)
                logger.debug("Published kline event: symbol=%s, timeframe=%s, close=%.2f",
                             symbol, event.timeframe, event.close)

            elif event_type == "fundingRate":
                event = FundingRateEvent(
                    type="funding_rate",
                    symbol=symbol,
                    funding_rate=float(message["r"]),
                    timestamp=timestamp,
                    data={}
                )
                await self.storage.save_funding_rate(event)
                await self.event_bus.publish("funding_rate", event)
                logger.debug("Published funding_rate event: symbol=%s, rate=%.6f",
                             symbol, event.funding_rate)

            elif event_type == "depthUpdate":
                event = OrderBookEvent(
                    type="order_book",
                    symbol=symbol,
                    bids=[(float(b[0]), float(b[1])) for b in message["b"]],
                    asks=[(float(a[0]), float(a[1])) for a in message["a"]],
                    timestamp=timestamp,
                    data={}
                )
                await self.event_bus.publish("order_book", event)
                logger.debug("Published order_book event: symbol=%s, bids=%d, asks=%d",
                             symbol, len(event.bids), len(event.asks))

        except Exception as e:
            logger.error("Error processing WebSocket message: %s", e)

    async def fetch_historical_data(self):
        """Lấy dữ liệu lịch sử để khởi tạo."""
        try:
            for symbol in self.settings.symbols:
                # Lấy kline
                klines = await self.exchange_client.get_klines(
                    symbol=symbol,
                    timeframe=self.settings.base_timeframe,
                    limit=self.settings.max_klines
                )
                for kline in klines:
                    event = KlineEvent(
                        type="kline",
                        symbol=symbol,
                        timeframe=self.settings.base_timeframe,
                        open_time=kline["open_time"],
                        close_time=kline["close_time"],
                        open=kline["open"],
                        high=kline["high"],
                        low=kline["low"],
                        close=kline["close"],
                        volume=kline["volume"],
                        num_trades=kline["num_trades"],
                        is_closed=True,
                        timestamp=kline["close_time"],
                        data={}
                    )
                    await self.storage.save_kline(event)

                # Lấy funding rate
                funding_rates = await self.exchange_client.get_funding_rates(symbol, limit=10)
                for rate in funding_rates:
                    event = FundingRateEvent(
                        type="funding_rate",
                        symbol=symbol,
                        funding_rate=rate["funding_rate"],
                        timestamp=rate["timestamp"],
                        data={}
                    )
                    await self.storage.save_funding_rate(event)

                logger.info("Fetched historical data for %s: %d klines, %d funding rates",
                            symbol, len(klines), len(funding_rates))

        except Exception as e:
            logger.error("Failed to fetch historical data: %s", e)

    async def run(self):
        """Chạy vòng lặp chính của hệ thống."""
        try:
            await self.initialize()
            await self.fetch_historical_data()
            tasks = [
                self.signal_generator.run(),
                self.trading_engine.run(),
                self.setup_websocket()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error("System error: %s", e)
        finally:
            if self.ws_session:
                await self.ws_session.close()
            logger.info("System shutdown")

async def main():
    system = TradingSystem()
    await system.run()

if __name__ == "__main__":
    asyncio.run(main())