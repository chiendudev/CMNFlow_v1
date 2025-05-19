import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from src.core.settings import Settings
from src.core.events import EventBus, SignalEvent, OrderEvent, MarkPriceEvent
from src.core.storage import Storage
from src.core.logging_config import get_logger, set_log_context
from src.trading.portfolio import Portfolio
from src.trading.risk import RiskManager
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType

logger = get_logger(__name__)

class TradingEngine:
    def __init__(self, settings: Settings, event_bus: EventBus, portfolio: Portfolio, risk_manager: RiskManager, storage: Storage):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.storage = storage
        self.active_orders: Dict[str, Order] = {}
        logger.info("Initialized TradingEngine for symbols: %s", settings.symbols)

    async def initialize(self):
        """Khởi tạo các subscriber bất đồng bộ."""
        set_log_context()
        await self._initialize_subscribers()
        logger.debug("TradingEngine subscribers initialized")

    async def _initialize_subscribers(self):
        """Đăng ký các sự kiện."""
        set_log_context()
        await self.event_bus.subscribe("signal", self._handle_signal, priority=1)
        await self.event_bus.subscribe("order", self._handle_order, priority=1)
        await self.event_bus.subscribe("mark_price", self._handle_mark_price, priority=2)

    async def _handle_signal(self, event: SignalEvent):
        """Xử lý tín hiệu giao dịch."""
        set_log_context(symbol=event.symbol, timeframe=event.timeframe)
        signal = event.data
        symbol = event.symbol
        signal_type = signal["type"]
        entry_price = signal["entry"]
        stop_loss = signal["stop_loss"]
        take_profit = signal["take_profit"]
        strategy = signal["strategy"]

        position_size = self.risk_manager.calculate_position_size(symbol, entry_price, stop_loss)
        if position_size <= 0:
            logger.warning("Invalid position size for %s: %.4f", symbol, position_size)
            return

        order_side = OrderSide.BUY if signal_type == "buy" else OrderSide.SELL
        position_side = PositionSide.LONG if signal_type == "buy" else PositionSide.SHORT
        order = Order(
            symbol=symbol,
            side=order_side,
            position_side=position_side,
            type=OrderType.MARKET,
            quantity=position_size,
            price=entry_price,
            reduce_only=False
        )

        oco_order = OCOOrder(
            symbol=symbol,
            side=OrderSide.SELL if signal_type == "buy" else OrderSide.BUY,
            position_side=position_side,
            quantity=position_size,
            stop_price=stop_loss,
            limit_price=take_profit
        )
        is_valid, reason = await self.risk_manager.check_risk(order, oco_order)
        if not is_valid:
            logger.warning("Risk check failed for %s: %s", symbol, reason)
            return

        try:
            if await self.portfolio.place_order(order):
                self.active_orders[order.order_id] = order
                logger.info("Placed order: symbol=%s, side=%s, quantity=%.4f, strategy=%s",
                            symbol, order_side, position_size, strategy)

                if await self.portfolio.place_oco_order(oco_order):
                    logger.info("Placed OCO order: symbol=%s, stop_price=%.2f, limit_price=%.2f",
                                symbol, stop_loss, take_profit)
                else:
                    logger.error("Failed to place OCO order for %s", symbol)
            else:
                logger.error("Failed to place order for %s", symbol)
        except Exception as e:
            logger.error("Error placing order for %s: %s", symbol, e)

    async def _handle_order(self, event: OrderEvent):
        """Xử lý sự kiện lệnh."""
        set_log_context(symbol=event.symbol)
        order = event.data
        order_id = order["order_id"]
        if order_id in self.active_orders:
            if order["status"] == "FILLED":
                logger.info("Order filled: symbol=%s, order_id=%s", event.symbol, order_id)
                del self.active_orders[order_id]
                await self.storage.save_order(order)
            elif order["status"] == "CANCELED":
                logger.info("Order canceled: symbol=%s, order_id=%s", event.symbol, order_id)
                del self.active_orders[order_id]

    async def _handle_mark_price(self, event: MarkPriceEvent):
        """Cập nhật vị thế và kiểm tra rủi ro."""
        set_log_context(symbol=event.symbol)
        symbol = event.symbol
        current_price = event.mark_price
        position = await self.portfolio.get_position(symbol)
        if position:
            new_stop = await self.risk_manager.update_trailing_stop(position, current_price)
            if new_stop:
                await self.storage.save_position_async(position)
                logger.debug("Updated trailing stop for %s: %.2f", symbol, new_stop)

            await self.risk_manager.reduce_position_if_needed(symbol, position.side)

    async def run(self):
        """Chạy TradingEngine."""
        logger.info("TradingEngine running")
        while True:
            await asyncio.sleep(self.settings.throttle_rate)