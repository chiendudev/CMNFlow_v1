

# async def main():
#
#     # settings = Settings()
#     # storage = DataStorage(settings)
#     # client = BinanceClient(settings.api_key, settings.api_secret)
#     # rest_client = BinanceRestClient(settings)
#     # portfolio = PortfolioManager(settings.trade_mode, MarginType.ISOLATED, settings.leverage)
#     # portfolio.set_exchange_client(client)
#     #
#     # # Khởi tạo dữ liệu lịch sử
#     # tasks = [rest_client.initialize_historical_data(symbol, storage) for symbol in settings.symbols]
#     # await asyncio.gather(*tasks)
#     #
#     # ws_client = WebSocketClient(settings, storage, portfolio)
#     # save_task = asyncio.create_task(periodic_save(storage, settings.save_interval))
#     #
#     #
#     # try:
#     #     await ws_client.run()
#     # except KeyboardInterrupt:
#     #     logger.info("Dừng chương trình...")
#     #     save_task.cancel()
#     #     await storage.save_all()
#     # except Exception as e:
#     #     logger.error("Lỗi chính: %s", e, exc_info=True)
#     #     save_task.cancel()
#     #     await storage.save_all()

import asyncio
from logging_config import setup_logging
import logging
from src.core.settings import Settings
from src.core.events import EventBus
from src.core.logging_config import setup_logging


import aiohttp


logger = logging.getLogger(__name__)
if __name__ == "__main__":
    settings = Settings()
    setup_logging(settings)

    print("MAIN RUN")