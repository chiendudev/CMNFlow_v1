import asyncio
import logging
from typing import Optional, Dict
from collections import deque
import numpy as np
from src.core.events import EventBus, KlineEvent, FundingRateEvent, TradeEvent
from src.core.settings import Settings
from src.trading.portfolio import Portfolio
from src.trading.risk import RiskManager
from src.core.storage import Storage
from src.strategy.indicators import Indicators
from src.strategy.confluence import Confluence

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self, settings: Settings, event_bus: EventBus, portfolio: Portfolio, storage: Storage, risk_manager: RiskManager):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.storage = storage
        self.risk_manager = risk_manager
        self.confluence_count = 0
        self.trade_cache = {symbol: deque(maxlen=5000) for symbol in settings.symbols}
        self.kline_cache = {symbol: {tf: deque(maxlen=100) for tf in settings.timeframes} for symbol in settings.symbols}
        self.indicators = Indicators()
        self.confluence = Confluence(settings, self.indicators)
        self.min_trades = getattr(settings, 'min_trades', 500)
        self.max_trades = getattr(settings, 'max_trades', 1000)
        self.volatility_threshold = getattr(settings, 'volatility_threshold', 0.01)
        self.max_timeframe_ms = 5 * 60 * 1000

    async def initialize(self):
        await self._initialize_subscribers()
        logger.info("SignalGenerator initialized")

    async def _initialize_subscribers(self):
        await self.event_bus.subscribe("kline", self._handle_kline, priority=2)
        await self.event_bus.subscribe("funding_rate", self._handle_funding_rate, priority=1)
        await self.event_bus.subscribe("trade", self._handle_trade, priority=1)

    async def _handle_kline(self, event: KlineEvent):
        if not event.is_closed:
            return
        symbol = event.symbol
        timeframe = event.timeframe
        self.kline_cache[symbol][timeframe].append(event)
        logger.debug(f"Processing kline: symbol={symbol}, timeframe={timeframe}, close={event.close}")

    async def _handle_funding_rate(self, event: FundingRateEvent):
        logger.debug(f"Processing funding_rate: symbol={event.symbol}, rate={event.funding_rate}")

    async def _handle_trade(self, event: TradeEvent):
        symbol = event.symbol
        timestamp = event.timestamp
        self.trade_cache[symbol].append(event)
        logger.debug(f"Processing trade: symbol={symbol}, price={event.data['p']}, quantity={event.data['q']}")

        trades = list(self.trade_cache[symbol])
        target_trades = self.min_trades
        if len(trades) < target_trades:
            additional_trades = await self.storage.get_agg_trades_by_count(
                symbol, timestamp, target_trades - len(trades)
            )
            trades = additional_trades + trades

        if len(trades) < target_trades:
            logger.debug(f"Insufficient trades for {symbol}: got {len(trades)}, need {target_trades}")
            return

        prices = np.array([float(t.data["p"]) for t in trades])
        max_price, min_price = prices.max(), prices.min()
        avg_price = prices.mean()
        volatility = (max_price - min_price) / avg_price if avg_price > 0 else 0

        if volatility > self.volatility_threshold:
            target_trades = self.min_trades  # Scalping
        elif volatility < 0.005:
            target_trades = 5000  # 1h
        else:
            target_trades = 2000  # Swing
        if len(trades) > target_trades:
            trades = trades[-target_trades:]
        elif len(trades) < target_trades:
            additional_trades = await self.storage.get_agg_trades_by_count(
                symbol, timestamp, target_trades - len(trades)
            )
            trades = additional_trades + trades
            if len(trades) > target_trades:
                trades = trades[-target_trades:]

        max_time = 5 * 60 * 1000 if volatility > 0.01 else 15 * 60 * 1000
        if trades:
            earliest_time = min(t.timestamp for t in trades)
            if timestamp - earliest_time > max_time:
                trades = [t for t in trades if timestamp - t.timestamp <= max_time]

        if len(trades) < self.min_trades:
            logger.debug(f"Insufficient trades after trimming for {symbol}: got {len(trades)}")
            return

        signal_data = {
            "symbol": symbol,
            "volatility": volatility,
            "trades": len(trades)
        }

        # Đánh giá confluence cho mỗi khung
        for timeframe in self.settings.timeframes:
            if not self.kline_cache[symbol].get(timeframe):
                continue
            klines = [{"close": k.close, "volume": k.volume, "trades": [t.__dict__ for t in trades]}
                      for k in self.kline_cache[symbol][timeframe]]
            funding_rate = None  # Cần lấy từ storage hoặc event_bus
            confluence_result = await self.confluence.evaluate(symbol, timeframe, klines, trades)
            if confluence_result["is_valid"]:
                signal_data["direction"] = confluence_result["direction"]
                signal_data["strategy"] = confluence_result["strategy"]
                signal_data[f"confluence_{timeframe}"] = confluence_result
                break  # Ưu tiên khung có tín hiệu hợp lệ đầu tiên

        if "direction" in signal_data:
            risk_params = await self.risk_manager.evaluate_risk(symbol, signal_data["direction"])
            signal_data.update(risk_params)
            await self.event_bus.publish("signal", signal_data)
            logger.info(f"Published signal for {symbol}: strategy={signal_data['strategy']}, direction={signal_data['direction']}, "
                        f"volatility={volatility:.4f}")

    async def run(self):
        while True:
            await asyncio.sleep(self.settings.throttle_rate)