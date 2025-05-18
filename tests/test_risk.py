import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from src.core.settings import Settings
from src.core.events import EventBus, MarkPriceEvent
from src.core.storage import Storage
from src.trading.portfolio import Portfolio, Position
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus
from src.trading.risk import RiskManager
from src.data.kline import Kline


@pytest.fixture
def settings(tmp_path):
    settings = Settings()
    settings.symbols = ["BTCUSDT", "ETHUSDT"]
    settings.db_path = str(tmp_path / "test_trading.db")
    settings.max_risk_per_trade = 0.01
    settings.max_margin_ratio = 0.80
    settings.correlation_threshold = 0.80
    settings.volatility_threshold = 0.02
    settings.atr_period = 14
    settings.sl_atr_multiplier = 2.0
    settings.tp_atr_multiplier = 4.0
    settings.trailing_stop_distance = 100.0
    return settings


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def storage(settings, event_bus):
    return Storage(settings, event_bus)


@pytest.fixture
def portfolio(settings, event_bus, storage):
    exchange_client = AsyncMock()
    portfolio = Portfolio(settings, event_bus, exchange_client)
    portfolio.storage = storage
    portfolio.balance = 1000.0
    return portfolio


@pytest.fixture
def risk_manager(settings, event_bus, portfolio, storage):
    return RiskManager(settings, event_bus, portfolio, storage)


@pytest.mark.asyncio
async def test_position_size(risk_manager, storage):
    # Mock klines để tính ATR
    klines = [
        Kline(symbol="BTCUSDT", timeframe="5m", open_time=i * 300000, close_time=(i + 1) * 300000,
              open=50000, high=50500, low=49500, close=50200, volume=1000, num_trades=100)
        for i in range(15)
    ]
    storage.save_klines("BTCUSDT", klines)

    size = risk_manager.calculate_position_size("BTCUSDT", entry_price=50000, stop_loss=49000)
    assert 0 < size <= (1000 * 10) / 50000  # Trong giới hạn leverage
    assert size > 0  # Kích thước hợp lệ


@pytest.mark.asyncio
async def test_sl_tp_calculation(risk_manager, storage):
    klines = [
        Kline(symbol="BTCUSDT", timeframe="5m", open_time=i * 300000, close_time=(i + 1) * 300000,
              open=50000, high=50500, low=49500, close=50200, volume=1000, num_trades=100)
        for i in range(15)
    ]
    storage.save_klines("BTCUSDT", klines)

    sl, tp = risk_manager.calculate_sl_tp("BTCUSDT", entry_price=50000, side="LONG")
    assert sl < 50000
    assert tp > 50000
    assert abs(tp - 50000) > abs(sl - 50000)  # TP xa hơn SL


@pytest.mark.asyncio
async def test_trailing_stop(risk_manager, portfolio, storage):
    position = Position(
        symbol="BTCUSDT",
        side="LONG",
        quantity=0.001,
        entry_price=50000,
        current_price=51000,
        leverage=10.0
    )
    portfolio.positions["BTCUSDT"] = {"LONG": position}
    new_stop = risk_manager.update_trailing_stop(position, current_price=51000)
    assert new_stop == 51000 - risk_manager.trailing_stop_distance
    assert position.stop_loss == new_stop


@pytest.mark.asyncio
async def test_risk_check(risk_manager, portfolio):
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        type=OrderType.MARKET,
        quantity=0.001,
        price=50000
    )
    is_safe, reason = await risk_manager.check_risk(order)
    assert is_safe
    assert reason == "Risk check passed"


@pytest.mark.asyncio
async def test_correlation_risk(risk_manager, storage):
    # Mock klines cho BTCUSDT và ETHUSDT với độ tương quan cao
    btc_klines = [
        Kline(symbol="BTCUSDT", timeframe="5m", open_time=i * 300000, close_time=(i + 1) * 300000,
              open=50000 + i * 100, high=50500 + i * 100, low=49500 + i * 100, close=50200 + i * 100, volume=1000,
              num_trades=100)
        for i in range(50)
    ]
    eth_klines = [
        Kline(symbol="ETHUSDT", timeframe="5m", open_time=i * 300000, close_time=(i + 1) * 300000,
              open=3000 + i * 6, high=3050 + i * 6, low=2950 + i * 6, close=3020 + i * 6, volume=1000, num_trades=100)
        for i in range(50)
    ]
    storage.save_klines("BTCUSDT", btc_klines)
    storage.save_klines("ETHUSDT", eth_klines)
    portfolio.positions["ETHUSDT"] = {
        "LONG": Position(symbol="ETHUSDT", side="LONG", quantity=0.1, entry_price=3000, leverage=10.0)}

    is_safe = risk_manager.check_correlation_risk("BTCUSDT")
    assert not is_safe  # Tương quan cao, từ chối mở vị thế