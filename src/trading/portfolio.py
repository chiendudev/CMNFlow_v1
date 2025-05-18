import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List

from src.core.events import PositionEvent, OrderEvent
from src.core.settings import Settings
from src.core.custom_logging import get_logger, set_log_context
from src.trading.orders import Order, OCOOrder
from src.exchange.client import ExchangeClient

logger = get_logger(__name__)

class Position:
    def __init__(self, symbol: str, side: str, quantity: float, entry_price: float, leverage: float):
        self.symbol = symbol
        self.side = side  # LONG or SHORT
        self.quantity = quantity
        self.entry_price = entry_price
        self.leverage = leverage
        self.stop_loss: Optional[float] = None
        self.take_profit: Optional[float] = None
        set_log_context(symbol=symbol)

class Portfolio:
    def __init__(self, settings: Settings, exchange_client: ExchangeClient):
        from src.core.events import EventBus, SignalEvent, MarkPriceEvent, LiquidationEvent, OrderEvent
        self.settings = settings
        self.exchange_client = exchange_client
        self.event_bus = EventBus(settings)
        self.positions: Dict[str, Dict[str, Position]] = {}  # symbol -> side -> Position
        self.event_bus.subscribe("signal", self._handle_signal, priority=2)
        self.event_bus.subscribe("mark_price", self._handle_mark_price, priority=2)
        self.event_bus.subscribe("liquidation", self._handle_liquidation, priority=2)
        self.event_bus.subscribe("order", self._handle_order, priority=2)
        logger.info("Initialized Portfolio for symbols: %s", settings.symbols)

    async def _handle_signal(self, event: 'SignalEvent') -> None:
        set_log_context(symbol=event.symbol, timeframe=event.timeframe)
        signal = event.signal
        symbol = event.symbol
        logger.debug("Processing signal: symbol=%s, type=%s, entry=%.2f", symbol, signal["type"], signal["entry"])

        if signal["type"] == "buy":
            side = "LONG"
        elif signal["type"] == "sell":
            side = "SHORT"
        else:
            logger.warning("Invalid signal type: %s", signal["type"])
            return

        position = Position(
            symbol=symbol,
            side=side,
            quantity=self.settings.trade_quantity,
            entry_price=signal["entry"],
            leverage=self.settings.leverage
        )
        position.stop_loss = signal["stop_loss"]
        position.take_profit = signal["take_profit"]

        if symbol not in self.positions:
            self.positions[symbol] = {}
        self.positions[symbol][side] = position

        order = Order(
            symbol=symbol,
            side=side,
            quantity=self.settings.trade_quantity,
            price=signal["entry"],
            position_side=side
        )
        await self.event_bus.publish("order", OrderEvent(
            type="order",
            symbol=symbol,
            order=order,
            timestamp=int(datetime.now().timestamp() * 1000),
            data={}
        ))
        logger.info("Placed order: symbol=%s, side=%s, price=%.2f", symbol, side, signal["entry"])

    async def _handle_mark_price(self, event: 'MarkPriceEvent') -> None:
        set_log_context(symbol=event.symbol)
        for side, position in self.positions.get(event.symbol, {}).items():
            if position.stop_loss and event.mark_price <= position.stop_loss:
                logger.info("Stop loss triggered: symbol=%s, side=%s, price=%.2f", event.symbol, side, event.mark_price)
                await self.close_position(event.symbol, side)
            elif position.take_profit and event.mark_price >= position.take_profit:
                logger.info("Take profit triggered: symbol=%s, side=%s, price=%.2f", event.symbol, side, event.mark_price)
                await self.close_position(event.symbol, side)

    async def _handle_liquidation(self, event: 'LiquidationEvent') -> None:
        set_log_context(symbol=event.symbol)
        if event.symbol in self.positions and event.side in self.positions[event.symbol]:
            logger.warning("Liquidation detected: symbol=%s, side=%s, price=%.2f", event.symbol, event.side, event.price)
            await self.close_position(event.symbol, event.side)

    async def _handle_order(self, event: 'OrderEvent') -> None:
        set_log_context(symbol=event.symbol)
        order = event.order
        logger.debug("Processing order: symbol=%s, side=%s, price=%.2f", order.symbol, order.side, order.price)
        # Thêm logic xử lý order nếu cần

    async def close_position(self, symbol: str, side: str) -> None:
        if symbol in self.positions and side in self.positions[symbol]:
            position = self.positions[symbol][side]
            logger.info("Closing position: symbol=%s, side=%s, quantity=%.4f", symbol, side, position.quantity)
            del self.positions[symbol][side]
            if not self.positions[symbol]:
                del self.positions[symbol]
            await self.event_bus.publish("position", PositionEvent(
                type="position",
                symbol=symbol,
                position=position,
                action="CLOSE",
                timestamp=int(datetime.now().timestamp() * 1000),
                data={}
            ))

    async def get_margin_ratio(self) -> float:
        try:
            account_info = await self.exchange_client.get_account_info()
            margin_ratio = account_info.get("marginRatio", 0.0)
            logger.debug("Margin ratio: %.2f%%", margin_ratio * 100)
            return margin_ratio
        except Exception as e:
            logger.error("Failed to get margin ratio: %s", e)
            return 0.0

    async def run(self) -> None:
        logger.info("Portfolio running")
        while True:
            await asyncio.sleep(self.settings.throttle_rate)