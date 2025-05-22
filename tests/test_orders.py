import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Optional
from src.core.settings import Settings
from src.exchange.client import ExchangeClient
from src.trading.orders import Order
from src.trading.enums import OrderSide, OrderType, PositionSide, OrderStatus
from src.trading.order_manager import OrderManager
from src.utils.exchange_info import ExchangeInfo

# Cấu hình pytest để hỗ trợ asyncio
pytest_plugins = ['pytest_asyncio']

@pytest.mark.asyncio
async def test():
    setting = Settings()
    setting.api_key = 'a49a6fa8cf4a82c38606625cf56bbfae4cfdd94fd45cc0b24cb30b409096257f'
    setting.api_secret = 'eadf55a688758a5cf382217d070e632ec12bb6bffef48653446a71521cc442b9'
    setting.backtest_mode = True
    exchange_info = ExchangeInfo()

    client = ExchangeClient(setting)
    await exchange_info.fetch_exchange_info(client)
    order_manager = OrderManager(client, setting, exchange_info)
    order = Order(
        symbol='BTCUSDT',
        side= OrderSide.SELL,
        position_side= PositionSide.SHORT,
        type= OrderType.LIMIT,
        quantity=0.01002,
        price=104275.3
    )
    respose = await order_manager.send_order('BTCUSDT', order)
    assert respose is not None

@pytest.mark.asyncio
async def test_get_bracket():
    pass

if __name__ == "__main__":
    asyncio.run(test)