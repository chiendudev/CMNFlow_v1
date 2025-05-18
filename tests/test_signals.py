import pytest
import asyncio
from unittest.mock import AsyncMock
from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent
from src.trading.portfolio import Portfolio
from src.strategy.signals import SignalGenerator

@pytest.fixture
def settings():
    settings = Settings()
    settings.log_level = "DEBUG"
    return settings

@pytest.fixture
async def signal_generator(settings):
    event_bus = EventBus(settings)
    portfolio = Portfolio(settings, event_bus, AsyncMock())
    return SignalGenerator(settings, event_bus, portfolio)

@pytest.mark.asyncio
async def test_handle_kline(signal_generator, settings):
    handler = AsyncMock()
    await signal_generator.event_bus.subscribe("signal", handler, priority=1)
    event = KlineEvent(
        type="kline",
        symbol="BTCUSDT",
        data={},
        timestamp=1625097600000,
        timeframe="5m",
        open_time=1625097600000,
        close_time=1625097900000,
        open=50000.0,
        high=50500.0,
        low=49500.0,
        close=50200.0,
        volume=1000.0,
        num_trades=100,
        is_closed=True
    )
    await signal_generator._handle_kline(event)
    handler.assert_called()