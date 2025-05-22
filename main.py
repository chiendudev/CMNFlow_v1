import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, FundingRateEvent, OrderBookEvent
from src.core.storage import Storage
from src.core.logging_config import get_logger, setup_logging
from src.exchange.client import ExchangeClient
from src.trading.enums import KlineIntervals
from src.trading.portfolio import Portfolio
from src.trading.risk import RiskManager
from src.engine import TradingEngine
from src.strategy.signals import SignalGenerator
from src.exchange.websocket import WebSocketClient  # Import WebSocketClient
from src.utils.user_data_api import UserDataApi

logger = get_logger(__name__)

# class TradingSystem:
#     def __init__(self):
#         self.settings = Settings()
#         setup_logging(self.settings)
#         self.event_bus = EventBus(self.settings)
#         self.exchange_client = ExchangeClient(self.settings)
#         self.storage = Storage(self.settings, self.event_bus)
#         self.portfolio = Portfolio(self.settings, self.exchange_client, self.event_bus)
#         self.risk_manager = RiskManager(self.settings, self.event_bus, self.portfolio, self.storage)
#         self.signal_generator = SignalGenerator(
#             self.settings, self.event_bus, self.portfolio, self.storage, self.risk_manager
#         )
#         self.trading_engine = TradingEngine(
#             self.settings, self.event_bus, self.portfolio, self.risk_manager, self.storage
#         )
#         self.websocket_client = WebSocketClient(self.settings, self.event_bus)
#         logger.info("Initialized TradingSystem with symbols=%s, timeframes=%s",
#                     self.settings.symbols, self.settings.timeframes)
#
#     async def initialize(self):
#         """Khởi tạo database, subscribers, và WebSocket."""
#         try:
#             await self.storage.initialize()
#             await self.portfolio.initialize()
#             await self.risk_manager.initialize()
#             await self.signal_generator.initialize()
#             await self.trading_engine.initialize()
#             logger.info("System initialized successfully")
#         except Exception as e:
#             logger.error("Initialization failed: %s", e, exc_info=True)
#             raise
#
#     @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=10))
#     async def fetch_historical_data(self):
#         """Lấy dữ liệu lịch sử từ API."""
#         try:
#             required_klines = max(self.settings.rsi_period, self.settings.ema_slow_period, self.settings.max_klines)
#             end_time = datetime.now()
#             start_time = end_time - timedelta(days=30)  # Lấy 30 ngày dữ liệu
#             start_time_str = start_time.strftime("%d/%m/%Y")
#             end_time_str = end_time.strftime("%d/%m/%Y")
#
#             # Đảm bảo base_timeframe khớp với KlineIntervals
#             try:
#                 interval = KlineIntervals(self.settings.base_timeframe)
#             except ValueError:
#                 logger.error(f"Invalid base_timeframe: {self.settings.base_timeframe}")
#                 raise ValueError(
#                     f"base_timeframe must be a valid KlineIntervals value, got {self.settings.base_timeframe}")
#
#             for symbol in self.settings.symbols:
#                 # Lấy kline
#                 klines = await self.exchange_client.fetch_klines(
#                     symbol=symbol,
#                     interval=interval,
#                     start_time=start_time_str,
#                     end_time=end_time_str
#                 )
#                 logger.info(f"Fetched {len(klines)} klines for {symbol}")
#                 for kline in klines:
#                     event = KlineEvent(
#                         type="kline",
#                         symbol=symbol,
#                         timeframe=kline.timeframe,
#                         open_time=kline.open_time,
#                         close_time=kline.close_time,
#                         open=kline.open,
#                         high=kline.high,
#                         low=kline.low,
#                         close=kline.close,
#                         volume=kline.volume,
#                         num_trades=kline.num_trades,
#                         is_closed=True,
#                         timestamp=kline.close_time,
#                         data={}
#                     )
#                     await self.storage.save_kline(event)
#
#                 # Lấy funding rate
#                 funding_rates = await self.exchange_client.fetch_funding_rate(
#                     symbol=symbol,
#                     start_time=start_time_str,
#                     end_time=end_time_str
#                 )
#                 logger.info(f"Fetched {len(funding_rates)} funding rates for {symbol}")
#                 for rate in funding_rates:
#                     event = FundingRateEvent(
#                         type="funding_rate",
#                         symbol=symbol,
#                         funding_rate=float(rate["rate"]),
#                         timestamp=rate["time"],
#                         funding_time=rate["time"],
#                         data={}
#                     )
#                     await self.storage.save_funding_rate(event)
#
#                 logger.info("Completed historical data fetch for %s: %d klines, %d funding rates",
#                             symbol, len(klines), len(funding_rates))
#         except Exception as e:
#             logger.error("Failed to fetch historical data: %s", e, exc_info=True)
#             raise
#
#     async def run(self):
#         """Chạy vòng lặp chính của hệ thống."""
#         shutdown_reason = "unknown"
#         try:
#             await self.initialize()
#             await self.fetch_historical_data()
#             tasks = [
#                 self.signal_generator.run(),
#                 self.trading_engine.run(),
#                 self.websocket_client.run()
#             ]
#             await asyncio.gather(*tasks, return_exceptions=True)
#         except Exception as e:
#             shutdown_reason = f"Error: {str(e)}"
#             logger.error(f"System error: {e}", exc_info=True)
#         finally:
#             logger.info(f"Shutting down system: reason={shutdown_reason}, portfolio_state=_")

from src.trading.orders import Order
from src.trading.enums import OrderSide, PositionSide, OrderType
from src.trading.position import Position
from src.trading.portfolio import Portfolio
from src.trading.order_manager import OrderManager
from src.utils.exchange_info import ExchangeInfo
from src.utils.symbol_info import SymbolInfo
async def main():
    # system = TradingSystem()
    # await system.run()
    setting = Settings()
    setting.api_key = 'a49a6fa8cf4a82c38606625cf56bbfae4cfdd94fd45cc0b24cb30b409096257f'
    setting.api_secret = 'eadf55a688758a5cf382217d070e632ec12bb6bffef48653446a71521cc442b9'
    setting.backtest_mode = True
    client = ExchangeClient(setting)
    exchange_info = ExchangeInfo(client)
    await exchange_info.initial()
    user_api = UserDataApi(setting, client)

    symbol_info = SymbolInfo(symbol='BTCUSDT')
    await symbol_info.initial_symbol_info(exchange_info, user_api)
    print(symbol_info.to_dict())



if __name__ == "__main__":
    asyncio.run(main())