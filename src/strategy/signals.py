import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.core.settings import Settings
from src.core.events import EventBus, SignalEvent, KlineEvent
from src.core.storage import Storage
from src.core.logging_config import get_logger, set_log_context
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType
from src.trading.portfolio import Portfolio
from src.trading.risk import RiskManager
from src.strategy.confluence import Confluence
from src.strategy.trade_analyzer import TradeAnalyzer

logger = get_logger(__name__)


class SignalGenerator:
    def __init__(
            self,
            settings: Settings,
            event_bus: EventBus,
            portfolio: Portfolio,
            storage: Storage,
            risk_manager: RiskManager
    ):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.storage = storage
        self.risk_manager = risk_manager
        self.confluence = Confluence(settings, storage)
        self.trade_analyzer = TradeAnalyzer(settings, storage)
        self._initialize_subscribers()
        logger.info("Initialized SignalGenerator with symbols=%s, timeframes=%s",
                    settings.symbols, settings.timeframes)

    async def _initialize_subscribers(self):
        """Đăng ký các sự kiện."""
        set_log_context()
        await self.event_bus.subscribe("kline", self._handle_kline, priority=2)

    async def _handle_kline(self, event: KlineEvent):
        """Xử lý sự kiện kline để tạo tín hiệu."""
        if not event.is_closed:
            return

        symbol = event.symbol
        timeframe = event.timeframe
        set_log_context(symbol=symbol, timeframe=timeframe)

        try:
            signals = await self.generate_signals(symbol, timeframe)
            for signal in signals:
                signal_event = SignalEvent(
                    type="signal",
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=int(datetime.now().timestamp() * 1000),
                    data=signal
                )
                await self.event_bus.publish("signal", signal_event)
                logger.info("Generated %s signal: symbol=%s, entry=%.2f, sl=%.2f, tp=%.2f, strategy=%s",
                            signal["type"], symbol, signal["entry"], signal["stop_loss"], signal["take_profit"],
                            signal["strategy"])
        except Exception as e:
            logger.error("Error generating signals for %s: %s", symbol, e)

    async def generate_signals(self, symbol: str, timeframe: str) -> List[Dict[str, Any]]:
        """Tạo tín hiệu giao dịch dựa trên Confluence và TradeAnalyzer."""
        signals = []

        # Lấy dữ liệu
        klines = self.storage.get_klines(symbol, timeframe, limit=self.settings.max_klines)
        if len(klines) < max(self.settings.rsi_period, self.settings.ema_slow_period):
            logger.warning("Insufficient klines for %s: got %d, need %d", symbol, len(klines),
                           max(self.settings.rsi_period, self.settings.ema_slow_period))
            return signals

        trades = await self.trade_analyzer.get_trades(symbol)
        if not trades:
            logger.debug("No trades available for %s", symbol)
            return signals

        # Đánh giá Confluence
        confluence_result = await self.confluence.evaluate(symbol, timeframe, klines, trades)
        if not confluence_result.is_valid or confluence_result.condition_count < self.settings.min_confluence_count:
            logger.debug("Confluence invalid for %s: is_valid=%s, condition_count=%d",
                         symbol, confluence_result.is_valid, confluence_result.condition_count)
            return signals

        # Tạo tín hiệu
        direction = confluence_result.direction
        strategy = confluence_result.strategy
        current_price = klines[-1].close

        # Tính SL/TP
        stop_loss, take_profit = self.risk_manager.calculate_sl_tp(
            symbol, current_price, "LONG" if direction == "buy" else "SHORT"
        )
        if stop_loss == current_price or take_profit == current_price:
            logger.warning("Invalid SL/TP for %s: SL=%.2f, TP=%.2f", symbol, stop_loss, take_profit)
            return signals

        # Tạo lệnh mẫu để kiểm tra rủi ro
        position_size = self.risk_manager.calculate_position_size(symbol, current_price, stop_loss)
        if position_size <= 0:
            logger.warning("Invalid position size for %s: %.4f", symbol, position_size)
            return signals

        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if direction == "buy" else OrderSide.SELL,
            position_side=PositionSide.LONG if direction == "buy" else PositionSide.SHORT,
            type=OrderType.MARKET,
            quantity=position_size,
            price=current_price,
            reduce_only=False
        )

        # Kiểm tra rủi ro
        is_valid, reason = await self.risk_manager.check_risk(order)
        if not is_valid:
            logger.warning("Risk check failed for %s: %s", symbol, reason)
            return signals

        # Tạo tín hiệu
        signal = {
            "type": direction,
            "entry": current_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "strategy": strategy,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        signals.append(signal)

        # Tạo tín hiệu hedging nếu cần
        if self.settings.hedging_mode:
            hedge_direction = "sell" if direction == "buy" else "buy"
            hedge_stop_loss, hedge_take_profit = self.risk_manager.calculate_sl_tp(
                symbol, current_price, "SHORT" if hedge_direction == "sell" else "LONG"
            )
            if hedge_stop_loss == current_price or hedge_take_profit == current_price:
                logger.warning("Invalid hedge SL/TP for %s: SL=%.2f, TP=%.2f", symbol, hedge_stop_loss,
                               hedge_take_profit)
                return signals

            hedge_position_size = self.risk_manager.calculate_position_size(symbol, current_price, hedge_stop_loss)
            if hedge_position_size <= 0:
                logger.warning("Invalid hedge position size for %s: %.4f", symbol, hedge_position_size)
                return signals

            hedge_order = Order(
                symbol=symbol,
                side=OrderSide.SELL if hedge_direction == "sell" else OrderSide.BUY,
                position_side=PositionSide.SHORT if hedge_direction == "sell" else PositionSide.LONG,
                type=OrderType.MARKET,
                quantity=hedge_position_size,
                price=current_price,
                reduce_only=False
            )

            is_valid, reason = await self.risk_manager.check_risk(hedge_order)
            if is_valid:
                hedge_signal = {
                    "type": hedge_direction,
                    "entry": current_price,
                    "stop_loss": hedge_stop_loss,
                    "take_profit": hedge_take_profit,
                    "strategy": f"{strategy}_hedge",
                    "timestamp": int(datetime.now().timestamp() * 1000)
                }
                signals.append(hedge_signal)
                logger.debug("Generated hedge signal for %s: type=%s, strategy=%s",
                             symbol, hedge_direction, hedge_signal["strategy"])

        return signals

    async def run(self):
        """Chạy SignalGenerator."""
        logger.info("SignalGenerator running")
        while True:
            await asyncio.sleep(self.settings.throttle_rate)