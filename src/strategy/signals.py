from typing import List, Dict, Any, Optional
import asyncio
from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, FundingRateEvent, OrderBookEvent, SignalEvent
from src.core.storage import Storage
from src.trading.risk import RiskManager
from src.trading.portfolio import Portfolio
from src.strategy.indicators import Indicators
from src.strategy.confluence import Confluence
from src.core.logging_config import get_logger, set_log_context

logger = get_logger(__name__)

class SignalGenerator:
    def __init__(self, settings: Settings, event_bus: EventBus, portfolio: Portfolio, storage: Optional[Storage] = None, risk_manager: Optional[RiskManager] = None):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.storage = storage or Storage(settings, event_bus)
        self.risk_manager = risk_manager or RiskManager(settings, event_bus, portfolio, self.storage)
        self.indicators = Indicators()
        self.confluence = Confluence(settings, self.indicators)
        self.event_bus.subscribe("kline", self._handle_kline, priority=1)
        logger.info("Initialized SignalGenerator with timeframes=%s", self.settings.timeframes)

    async def _handle_kline(self, event: KlineEvent) -> None:
        set_log_context(symbol=event.symbol, timeframe=event.timeframe)
        if event.is_closed:
            signals = await self.generate_signals(event.symbol, event.timeframe)
            for signal in signals:
                await self.event_bus.publish("signal", SignalEvent(
                    type="signal",
                    symbol=event.symbol,
                    data=signal,
                    timestamp=event.timestamp,
                    timeframe=event.timeframe
                ))
                logger.debug("Published signal: symbol=%s, type=%s, entry=%.2f, strategy=%s",
                             event.symbol, signal["type"], signal["entry"], signal["strategy"])

    async def generate_signals(self, symbol: str, timeframe: str) -> List[Dict[str, Any]]:
        set_log_context(symbol=symbol, timeframe=timeframe)
        signals = []

        # Kiểm tra margin ratio
        margin_ratio = await self.portfolio.get_margin_ratio()
        if margin_ratio >= self.settings.max_margin_ratio:
            logger.warning("Margin ratio too high: %.2f%%, skipping signal generation", margin_ratio * 100)
            return signals

        # Lấy dữ liệu kline
        klines = await self.storage.get_klines(symbol, timeframe, limit=self.settings.max_klines)
        if len(klines) < max(self.settings.rsi_period, self.settings.ema_fast_period, self.settings.ema_slow_period):
            logger.warning("Insufficient kline data: got=%d", len(klines))
            return signals

        # Lấy funding rate gần nhất
        funding_rates = await self.storage.get_funding_rates(symbol, limit=1)
        funding_rate = funding_rates[0]["funding_rate"] if funding_rates else 0.0

        # Lấy order book
        order_book = None

        # Đánh giá confluence
        confluence_result = await self.confluence.evaluate(symbol, timeframe, klines, funding_rate, order_book)
        if not confluence_result["is_valid"]:
            return signals

        # Tính ATR
        atr = self.indicators.calculate_atr(klines, self.settings.atr_period)
        latest_kline = klines[0]
        signal_type = confluence_result["direction"]
        strategy = confluence_result["strategy"]

        # Điều chỉnh SL/TP theo chiến lược
        sl_atr_multiplier = self.settings.sl_atr_multiplier
        tp_atr_multiplier = self.settings.tp_atr_multiplier
        if strategy == "scalping":
            sl_atr_multiplier = 1.5
            tp_atr_multiplier = 2.0
        elif strategy == "volume_cluster":
            sl_atr_multiplier = 1.0
            tp_atr_multiplier = 3.0
        elif strategy == "breakout":
            sl_atr_multiplier = 2.0
            tp_atr_multiplier = 5.0
        # Momentum giữ mặc định (2.0, 4.0)

        # Tạo tín hiệu
        if signal_type == "buy" or (signal_type == "sell" and self.settings.hedging_mode):
            signal = {
                "type": signal_type,
                "entry": latest_kline["close"],
                "stop_loss": latest_kline["close"] - (atr * sl_atr_multiplier) if signal_type == "buy" else latest_kline["close"] + (atr * sl_atr_multiplier),
                "take_profit": latest_kline["close"] + (atr * tp_atr_multiplier) if signal_type == "buy" else latest_kline["close"] - (atr * tp_atr_multiplier),
                "strategy": strategy
            }
            signals.append(signal)
            logger.debug("Generated %s signal: entry=%.2f, sl=%.2f, tp=%.2f, strategy=%s",
                         signal_type, signal["entry"], signal["stop_loss"], signal["take_profit"], strategy)

        return signals

    async def run(self) -> None:
        logger.info("SignalGenerator running")
        while True:
            await asyncio.sleep(self.settings.throttle_rate)