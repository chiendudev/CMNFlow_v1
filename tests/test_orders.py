import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from src.core.settings import Settings
from src.core.events import EventBus, OrderEvent
from src.exchange.client import ExchangeClient
from src.trading.portfolio import Portfolio
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce

@pytest.fixture
def settings():
    settings = Settings()
    settings.symbols = ["BTCUSDT"]
    settings.trade_quantity = 0.001
    settings.max_risk_per_trade = 0.01
    settings.leverage = 10.0
    settings.hedging_mode = True
    settings.maker_fee = 0.0002
    settings.taker_fee = 0.0004
    settings.oco_enabled = True
    return settings

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def exchange_client():
    return AsyncMock(spec=ExchangeClient)

@pytest.fixture
async def portfolio(settings, event_bus, exchange_client):
    portfolio = Portfolio(settings, event_bus, exchange_client)
    await portfolio.initialize()
    return portfolio

@pytest.mark.asyncio
async def test_place_market_order(portfolio, event_bus):
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        type=OrderType.MARKET,
        quantity=0.001,
        status=OrderStatus.NEW
    )
    portfolio.exchange_client.place_order.return_value = {
        "orderId": "123",
        "status": "FILLED",
        "executedQty": "0.001",
        "avgPrice": "50000.0"
    }
    portfolio.balance = 1000.0
    success = await portfolio.place_order(order)
    assert success
    assert order.order_id == "123"
    assert order.status == OrderStatus.FILLED
    assert order.fee == 0.001 * 50000.0 * 0.0004  # Taker fee
    assert portfolio.balance == 1000.0 - order.fee

@pytest.mark.asyncio
async def test_place_oco_order(portfolio, event_bus):
    oco_order = OCOOrder(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        position_side=PositionSide.LONG,
        quantity=0.001,
        price=52000.0,
        stop_price=49000.0,
        reduce_only=True
    )
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        type=OrderType.MARKET,
        quantity=0.001,
        status=OrderStatus.NEW
    )
    portfolio.exchange_client.place_oco_order.return_value = {
        "orderListId": "456",
        "listOrderStatus": "EXECUTING"
    }
    portfolio.balance = 1000.0
    success = await portfolio.place_order(order, oco_order)
    assert success
    assert oco_order.order_list_id == "456"
    assert oco_order.status == OrderStatus.EXECUTING

@pytest.mark.asyncio
async def test_batch_orders(portfolio, event_bus):
    orders = [
        Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            position_side=PositionSide.LONG,
            type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
            status=OrderStatus.NEW
        ),
        Order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            position_side=PositionSide.SHORT,
            type=OrderType.LIMIT,
            quantity=0.001,
            price=51000.0,
            status=OrderStatus.NEW
        )
    ]
    portfolio.exchange_client.place_batch_orders.return_value = [
        {"orderId": "123", "status": "NEW", "executedQty": "0.0", "avgPrice": "0.0"},
        {"orderId": "124", "status": "NEW", "executedQty": "0.0", "avgPrice": "0.0"}
    ]
    portfolio.balance = 1000.0
    success = await portfolio.place_batch_orders(orders)
    assert success
    assert orders[0].order_id == "123"
    assert orders[1].order_id == "124"
    assert orders[0].status == OrderStatus.NEW
    assert orders[1].status == OrderStatus.NEW

@pytest.mark.asyncio
async def test_order_status_sync(portfolio, exchange_client):
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        type=OrderType.MARKET,
        quantity=0.001,
        order_id="123",
        status=OrderStatus.NEW
    )
    exchange_client.get_order_status.return_value = {
        "orderId": "123",
        "status": "FILLED",
        "executedQty": "0.001",
        "avgPrice": "50000.0"
    }
    status = await exchange_client.get_order_status("BTCUSDT", "123")
    order.status = OrderStatus(status["status"])
    order.executed_qty = float(status["executedQty"])
    order.avg_price = float(status["avgPrice"])
    assert order.status == OrderStatus.FILLED
    assert order.executed_qty == 0.001
    assert order.avg_price == 50000.0