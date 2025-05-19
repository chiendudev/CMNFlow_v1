import logging
from typing import Dict, Any, Optional
from datetime import datetime

from src.core.settings import Settings
from src.core.events import EventBus, OrderEvent
from src.core.logging_config import get_logger, set_log_context
from src.exchange.client import ExchangeClient
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide, OrderType

logger = get_logger(__name__)

class Position:
    def __init__(self, symbol: str, side: str, quantity: float, entry_price: float, stop_loss: float = None, trailing_stop: float = None):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.trailing_stop = trailing_stop

class Portfolio:
    def __init__(self, settings: Settings, exchange_client: ExchangeClient, event_bus: EventBus):
        self.settings = settings
        self.exchange_client = exchange_client
        self.balance: float = 100000.0  # Giả định số dư ban đầu
        self.positions: Dict[str, Position] = {}
        self.event_bus = event_bus
        logger.info("Initialized Portfolio for symbols: %s", settings.symbols)

    async def initialize(self):
        """Khởi tạo các subscriber bất đồng bộ."""
        set_log_context()
        await self._initialize_subscribers()
        logger.debug("Portfolio subscribers initialized")

    async def _initialize_subscribers(self):
        """Đăng ký sự kiện order."""
        set_log_context()
        await self.event_bus.subscribe("order", self._handle_order, priority=2)

    async def get_margin_ratio(self) -> float:
        """Lấy margin ratio từ ExchangeClient."""
        try:
            account_info = await self.exchange_client.get_account_info()
            margin_ratio = account_info.get("marginRatio", 0.0)
            logger.debug("Retrieved margin ratio: %.2f%%", margin_ratio * 100)
            return margin_ratio
        except Exception as e:
            logger.error("Failed to get margin ratio: %s", e)
            return 0.0

    async def get_position(self, symbol: str) -> Optional[Position]:
        """Lấy thông tin vị thế."""
        return self.positions.get(symbol)

    async def place_order(self, order: Order) -> bool:
        """Đặt lệnh qua ExchangeClient."""
        set_log_context(symbol=order.symbol)
        try:
            result = await self.exchange_client.place_order(
                symbol=order.symbol,
                side=order.side,
                position_side=order.position_side,
                type=order.type,
                quantity=order.quantity,
                price=order.price,
                reduce_only=order.reduce_only
            )
            order_id = result.get("order_id", "mock_order_id")
            order.order_id = order_id
            logger.info("Placed order: symbol=%s, side=%s, quantity=%.4f",
                        order.symbol, order.side, order.quantity)
            await self.event_bus.publish("order", OrderEvent(
                type="order",
                symbol=order.symbol,
                timestamp=int(datetime.now().timestamp() * 1000),
                data={
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "position_side": order.position_side,
                    "type": order.type,
                    "quantity": order.quantity,
                    "price": order.price,
                    "status": "FILLED",
                    "timestamp": int(datetime.now().timestamp() * 1000)
                }
            ))
            return True
        except Exception as e:
            logger.error("Failed to place order for %s: %s", order.symbol, e)
            return False

    async def place_oco_order(self, oco_order: OCOOrder) -> bool:
        """Đặt OCO order qua ExchangeClient."""
        set_log_context(symbol=oco_order.symbol)
        try:
            result = await self.exchange_client.place_oco_order(
                symbol=oco_order.symbol,
                side=oco_order.side,
                position_side=oco_order.position_side,
                quantity=oco_order.quantity,
                stop_price=oco_order.stop_price,
                limit_price=oco_order.limit_price
            )
            logger.info("Placed OCO order: symbol=%s, stop_price=%.2f, limit_price=%.2f",
                        oco_order.symbol, oco_order.stop_price, oco_order.limit_price)
            return True
        except Exception as e:
            logger.error("Failed to place OCO order for %s: %s", oco_order.symbol, e)
            return False

    async def _handle_order(self, event: OrderEvent):
        """Xử lý sự kiện order để cập nhật vị thế."""
        set_log_context(symbol=event.symbol)
        order = event.data
        if order["status"] == "FILLED":
            symbol = order["symbol"]
            side = order["position_side"]
            quantity = order["quantity"]
            price = order["price"]
            if order["reduce_only"]:
                if symbol in self.positions:
                    self.positions[symbol].quantity -= quantity
                    if self.positions[symbol].quantity <= 0:
                        del self.positions[symbol]
                    logger.info("Reduced position: symbol=%s, side=%s, quantity=%.4f",
                                symbol, side, quantity)
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=price
                )
                logger.info("Opened position: symbol=%s, side=%s, quantity=%.4f, entry_price=%.2f",
                            symbol, side, quantity, price)