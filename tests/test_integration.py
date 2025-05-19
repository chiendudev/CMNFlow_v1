import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, FundingRateEvent, OrderBookEvent, SignalEvent
from src.data.kline import Kline
from src.strategy.signals import SignalGenerator
from src.trading.portfolio import Portfolio
from src.exchange.client import ExchangeClient
from src.core.storage import Storage

@pytest.fixture
def settings():
    settings = Settings(
        symbols=["BTCUSDT"],
        api_key="test_api_key",
        api_secret="test_api_secret",
        timeframes=["5m"],
        base_timeframe="5m",
        ws_url="wss://fstream.binance.com/ws",
        enabled_events=["kline", "order_book", "funding_rate", "signal"],
        rsi_period=14,
        ema_fast_period=12,
        ema_slow_period=26,
        atr_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        min_confluence_count=3,
        sl_atr_multiplier=2.0,
        tp_atr_multiplier=4.0,
        funding_rate_threshold=-0.0001,
        max_margin_ratio=0.80,
        hedging_mode=True,
        max_klines=1000,
        throttle_rate=0.1,
        confluence_range_pct=0.01,
        trade_quantity=0.001,
        leverage=10.0,
        db_path="data/trading.db"
    )
    return settings

@pytest.fixture
def event_bus(settings):
    event_bus = EventBus(settings)
    event_bus.subscribe = AsyncMock()
    return event_bus

@pytest.fixture
def exchange_client():
    client = AsyncMock(spec=ExchangeClient)
    client.get_account_info = AsyncMock(return_value={"marginRatio": 0.50})  # Mock margin ratio
    return client

@pytest.fixture
def storage(settings, event_bus):
    storage = MagicMock(spec=Storage)
    storage._init_db = MagicMock()
    storage.get_klines = AsyncMock()
    storage.get_funding_rates = AsyncMock()
    return storage

@pytest.fixture
def portfolio(settings, event_bus, exchange_client):
    return Portfolio(settings, exchange_client)

@pytest.fixture
def signal_generator(settings, event_bus, portfolio, storage):
    signal_generator = SignalGenerator(settings, event_bus, portfolio, storage=storage)
    return signal_generator

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
        is_closed=True,
        trades=[
            {"trade_id": 1, "price": 50200.0, "quantity": 0.5, "timestamp": 1625097600000, "is_buyer_maker": True, "last_update": 1625097600000},
            {"trade_id": 2, "price": 50150.0, "quantity": 0.3, "timestamp": 1625097601000, "is_buyer_maker": True, "last_update": 1625097601000},
            {"trade_id": 3, "price": 50250.0, "quantity": 0.2, "timestamp": 1625097899000, "is_buyer_maker": False, "last_update": 1625097899000}
        ]
    )
    # Mock 26 klines để đáp ứng yêu cầu RSI, EMA
    klines = [
        {
            "open_time": 1625097600000 - i * 300000,  # Giảm 5 phút mỗi kline
            "close_time": 1625097900000 - i * 300000,
            "open": 50000.0 - i * 10,
            "high": 50500.0 - i * 10,
            "low": 49500.0 - i * 10,
            "close": 50200.0 - i * 10,
            "volume": 1000.0,
            "num_trades": 100,
            "trades": kline.trades if i == 0 else []  # Chỉ kline mới nhất có trades
        }
        for i in range(26)
    ]
    await event_bus.publish("kline", KlineEvent(
        type="kline",
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
        is_closed=True,
        timestamp=1625097600000,
        data={}
    ))
    await event_bus.publish("funding_rate", FundingRateEvent(
        type="funding_rate",
        symbol="BTCUSDT",
        funding_rate=-0.0002,
        timestamp=1625097600000,
        data={}
    ))

    with patch.object(signal_generator.indicators, 'calculate_rsi', return_value=25.0), \
         patch.object(signal_generator.indicators, 'calculate_ema', side_effect=[50250.0, 50100.0]), \
         patch.object(signal_generator.indicators, 'calculate_atr', return_value=100.0), \
         patch.object(signal_generator.indicators, 'find_support_resistance', return_value=(50100.0, 51000.0)), \
         patch.object(signal_generator.storage, 'get_klines', return_value=klines), \
         patch.object(signal_generator.storage, 'get_funding_rates', return_value=[{"funding_rate": -0.0002}]):
        signals = await signal_generator.generate_signals("BTCUSDT", "5m")
        print(f"Signals: {signals}")  # Debug

    assert len(signals) > 0
    signal = signals[0]
    assert signal["type"] == "buy"
    assert signal["entry"] == 50200.0
    assert signal["strategy"] == "scalping"  # Do buy_pressure và recent_velocity
    assert signal["stop_loss"] == 50050.0  # entry - 1.5*ATR
    assert signal["take_profit"] == 50400.0  # entry + 2*ATR

@pytest.mark.asyncio
async def test_no_signal_high_margin_ratio(signal_generator, event_bus, portfolio):
    portfolio.get_margin_ratio = AsyncMock(return_value=0.85)
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
        type="kline",
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
        is_closed=True,
        timestamp=1625097600000,
        data={}
    ))

    signals = await signal_generator.generate_signals("BTCUSDT", "5m")
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
        is_closed=True,
        trades=[
            {"trade_id": 1, "price": 50200.0, "quantity": 0.2, "timestamp": 1625097600000, "is_buyer_maker": False, "last_update": 1625097600000},
            {"trade_id": 2, "price": 50150.0, "quantity": 0.3, "timestamp": 1625097601000, "is_buyer_maker": False, "last_update": 1625097601000},
            {"trade_id": 3, "price": 50250.0, "quantity": 0.5, "timestamp": 1625097899000, "is_buyer_maker": True, "last_update": 1625097899000}
        ]
    )
    # Mock 26 klines
    klines = [
        {
            "open_time": 1625097600000 - i * 300000,
            "close_time": 1625097900000 - i * 300000,
            "open": 50000.0 - i * 10,
            "high": 50500.0 - i * 10,
            "low": 49500.0 - i * 10,
            "close": 50200.0 - i * 10,
            "volume": 1000.0,
            "num_trades": 100,
            "trades": kline.trades if i == 0 else []
        }
        for i in range(26)
    ]
    await event_bus.publish("kline", KlineEvent(
        type="kline",
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
        is_closed=True,
        timestamp=1625097600000,
        data={}
    ))
    await event_bus.publish("funding_rate", FundingRateEvent(
        type="funding_rate",
        symbol="BTCUSDT",
        funding_rate=0.0002,
        timestamp=1625097600000,
        data={}
    ))

    with patch.object(signal_generator.indicators, 'calculate_rsi', return_value=75.0), \
         patch.object(signal_generator.indicators, 'calculate_ema', side_effect=[50150.0, 50300.0]), \
         patch.object(signal_generator.indicators, 'calculate_atr', return_value=100.0), \
         patch.object(signal_generator.indicators, 'find_support_resistance', return_value=(49000.0, 50300.0)), \
         patch.object(signal_generator.storage, 'get_klines', return_value=klines), \
         patch.object(signal_generator.storage, 'get_funding_rates', return_value=[{"funding_rate": 0.0002}]):
        signals = await signal_generator.generate_signals("BTCUSDT", "5m")
        print(f"Signals: {signals}")  # Debug

    assert len(signals) > 0
    signal = signals[0]
    assert signal["type"] == "sell"
    assert signal["entry"] == 50200.0
    assert signal["strategy"] == "scalping"  # Do sell_pressure và recent_velocity
    assert signal["stop_loss"] == 50350.0  # entry + 1.5*ATR
    assert signal["take_profit"] == 50000.0  # entry - 2*ATR