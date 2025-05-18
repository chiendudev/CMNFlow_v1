import pytest
import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch
from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, OrderBookEvent, FundingRateEvent, OrderEvent
from src.core.storage import Storage
from src.data.kline import Kline, OrderBookSnapshot
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce
from src.trading.portfolio import Position

@pytest.fixture
def settings(tmp_path):
    settings = Settings()
    settings.symbols = ["BTCUSDT"]
    settings.timeframes = ["5m"]
    settings.db_path = str(tmp_path / "test_trading.db")
    settings.data_retention_days = 30
    settings.cache_size = 1000
    return settings

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def storage(settings, event_bus):
    return Storage(settings, event_bus)

@pytest.mark.asyncio
async def test_save_and_get_klines(storage):
    kline = Kline(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=1625097600000,
        close_time=1625097900000,
        open=50000.0,
        high=50500.0,
        low=49500.0,
        close=50200.0,
        volume=1000.0,
        num_trades=100
    )
    storage.save_klines("BTCUSDT", [kline])
    klines = storage.get_klines("BTCUSDT", "5m")
    assert len(klines) == 1
    assert klines[0].symbol == "BTCUSDT"
    assert klines[0].close == 50200.0

@pytest.mark.asyncio
async def test_save_and_get_order_book(storage):
    order_book = OrderBookSnapshot(
        bids=[(50100.0, 10.0)],
        asks=[(50300.0, 10.0)],
        timestamp=1625097600000
    )
    storage.save_order_book("BTCUSDT", order_book)
    with sqlite3.connect(storage.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM order_book WHERE symbol = ?", ("BTCUSDT",))
        row = cursor.fetchone()
        assert row[0] == "BTCUSDT"
        assert json.loads(row[2]) == [[50100.0, 10.0]]
        assert json.loads(row[3]) == [[50300.0, 10.0]]

@pytest.mark.asyncio
async def test_save_and_get_position(storage):
    position = Position(
        symbol="BTCUSDT",
        side="LONG",
        quantity=0.001,
        entry_price=50000.0,
        current_price=50200.0,
        leverage=10.0
    )
    storage.save_position(position)
    positions = storage.get_positions("BTCUSDT")
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].side == "LONG"
    assert positions[0].quantity == 0.001

@pytest.mark.asyncio
async def test_save_and_get_oco_order(storage):
    oco_order = OCOOrder(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        position_side=PositionSide.LONG,
        quantity=0.001,
        price=52000.0,
        stop_price=49000.0,
        order_list_id="456",
        status=OrderStatus.EXECUTING
    )
    storage.save_oco_order(oco_order)
    orders = storage.get_orders(symbol="BTCUSDT", is_oco=True)
    assert len(orders) == 2  # LIMIT và STOP_MARKET
    assert orders[0].is_oco
    assert orders[0].oco_list_id == "456"
    assert orders[1].type == OrderType.STOP_MARKET

@pytest.mark.asyncio
async def test_cleanup_old_data(storage):
    old_kline = Kline(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=int((datetime.now() - timedelta(days=40)).timestamp() * 1000),
        close_time=int((datetime.now() - timedelta(days=40)).timestamp() * 1000) + 300000,
        open=50000.0,
        high=50500.0,
        low=49500.0,
        rackspace_id="test_rackspace_id",
        close=50200.0,
        volume=1000.0,
        num_trades=100
    )
    storage.save_klines("BTCUSDT", [old_kline])
    storage.cleanup_old_data()
    klines = storage.get_klines("BTCUSDT", "5m")
    assert len(klines) == 0