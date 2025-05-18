import pytest
import asyncio
from pydantic_settings import BaseSettings
from unittest.mock import AsyncMock, patch
from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, OrderBookEvent, FundingRateEvent, SignalEvent, OrderBookSnapshot
from src.data.kline import Kline
from src.strategy.signals import SignalGenerator
from src.trading.portfolio import Portfolio
from src.exchange.client import ExchangeClient

@pytest.fixture
def settings():
    settings = Settings()
    settings.symbols = ["BTCUSDT"]
    settings.timeframes = ["5m"]
    settings.rsi_period = 14
    settings.ema_fast_period = 12
    settings.ema_slow_period = 26
    settings.atr_period = 14
    settings.rsi_oversold = 30.0
    settings.rsi_overbought = 70.0
    settings.min_confluence_count = 3
    settings.sl_atr_multiplier = 2.0
    settings.tp_atr_multiplier = 4.0
    settings.funding_rate_threshold = -0.0001
    return settings

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def exchange_client():
    return AsyncMock(spec=ExchangeClient)

@pytest.fixture
def portfolio(settings, event_bus, exchange_client):
    return Portfolio(settings, event_bus, exchange_client)

@pytest.fixture
def signal_generator(settings, event_bus, portfolio):
    return SignalGenerator(settings, event_bus, portfolio)

@pytest.mark.asyncio
async def test_generate_buy_signal(signal_generator, event_bus):
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
        num_trades=100,
        is_closed=True
    )
    await event_bus.publish("kline", KlineEvent(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=kline.open_time,
        close_time=kline.close_time,
        open=kline.open,
        high=kline.high,
        low=kline.low,
        close=kline.close,
        volume=kline.volume,
        num_trades=kline.num_trades,
        is_closed=True
    ))
    await event_bus.publish("funding_rate", FundingRateEvent("BTCUSDT", -0.0002, 1625097600000))
    await event_bus.publish("order_book", OrderBookEvent("BTCUSDT", [(50100, 10)], [(50300, 10)], 1625097600000))

    # Mock indicators
    with patch.object(signal_generator.indicators, 'rsi', return_value=25.0), \
         patch.object(signal_generator.indicators, 'ema', side_effect=[50250.0, 50100.0]), \
         patch.object(signal_generator.indicators, 'atr', return_value=100.0), \
         patch.object(signal_generator.indicators, 'find_support_resistance', return_value=(49000.0, 51000.0)):
        signals = signal_generator.generate_signals("BTCUSDT", "5m")

    assert len(signals) > 0
    signal = signals[0]
    assert signal["type"] == "buy"
    assert signal["entry"] == 50200.0
    assert signal["stop_loss"] == 50000.0  # entry - 2*ATR
    assert signal["take_profit"] == 50600.0  # entry + 4*ATR

@pytest.mark.asyncio
async def test_no_signal_high_margin_ratio(signal_generator, event_bus, portfolio):
    portfolio.get_margin_ratio = AsyncMock(return_value=85.0)
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
        num_trades=100,
        is_closed=True
    )
    await event_bus.publish("kline", KlineEvent(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=kline.open_time,
        close_time=kline.close_time,
        open=kline.open,
        high=kline.high,
        low=kline.low,
        close=kline.close,
        volume=kline.volume,
        num_trades=kline.num_trades,
        is_closed=True
    ))

    signals = signal_generator.generate_signals("BTCUSDT", "5m")
    assert len(signals) == 0

@pytest.mark.asyncio
async def test_hedging_signals(signal_generator, event_bus):
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
        num_trades=100,
        is_closed=True
    )
    await event_bus.publish("kline", KlineEvent(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=kline.open_time,
        close_time=kline.close_time,
        open=kline.open,
        high=kline.high,
        low=kline.low,
        close=kline.close,
        volume=kline.volume,
        num_trades=kline.num_trades,
        is_closed=True
    ))
    await event_bus.publish("funding_rate", FundingRateEvent("BTCUSDT", 0.0002, 1625097600000))

    # Mock indicators for sell signal
    with patch.object(signal_generator.indicators, 'rsi', return_value=75.0), \
         patch.object(signal_generator.indicators, 'ema', side_effect=[50150.0, 50300.0]), \
         patch.object(signal_generator.indicators, 'atr', return_value=100.0), \
         patch.object(signal_generator.indicators, 'find_support_resistance', return_value=(49000.0, 51000.0)):
        signals = signal_generator.generate_signals("BTCUSDT", "5m")

    assert len(signals) > 0
    signal = signals[0]
    assert signal["type"] == "sell"
    assert signal["entry"] == 50200.0
    assert signal["stop_loss"] == 50400.0  # entry + 2*ATR
    assert signal["take_profit"] == 49800.0  # entry - 4*ATR