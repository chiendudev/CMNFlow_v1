import asyncio
import logging

import aiohttp

from old.config.settings import Settings
from old.trading.enums import KlineIntervals
from old.data import DataStorage
from old.data.multi_timeframe_kline import MultiTimeFrameKline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def periodic_save(storage: DataStorage, interval: int):
    while True:
        await storage.save_all()
        await asyncio.sleep(interval)


async def main():

    async with aiohttp.ClientSession() as session:
        mtf = MultiTimeFrameKline('ETHUSDT', KlineIntervals.m5, [KlineIntervals.m15, KlineIntervals.m30, KlineIntervals.h1])
        await mtf.fetch_klines(session=session, settings=Settings(),start_time='1/5/2025', end_time='2/5/2025')
        print(mtf.kline_data)
    # settings = Settings()
    # storage = DataStorage(settings)
    # client = BinanceClient(settings.api_key, settings.api_secret)
    # rest_client = BinanceRestClient(settings)
    # portfolio = PortfolioManager(settings.trade_mode, MarginType.ISOLATED, settings.leverage)
    # portfolio.set_exchange_client(client)
    #
    # # Khởi tạo dữ liệu lịch sử
    # tasks = [rest_client.initialize_historical_data(symbol, storage) for symbol in settings.symbols]
    # await asyncio.gather(*tasks)
    #
    # ws_client = WebSocketClient(settings, storage, portfolio)
    # save_task = asyncio.create_task(periodic_save(storage, settings.save_interval))
    #
    #
    # try:
    #     await ws_client.run()
    # except KeyboardInterrupt:
    #     logger.info("Dừng chương trình...")
    #     save_task.cancel()
    #     await storage.save_all()
    # except Exception as e:
    #     logger.error("Lỗi chính: %s", e, exc_info=True)
    #     save_task.cancel()
    #     await storage.save_all()


if __name__ == "__main__":
    asyncio.run(main())