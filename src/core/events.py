import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable, Union
from dataclasses import dataclass
from datetime import datetime
from src.core.settings import Settings
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide
from src.trading.portfolio import Position

logger = logging.getLogger(__name__)

@dataclass
class Event:
    type: str
    symbol: str
    data: Any
    timestamp: int
    position_side: Optional[PositionSide] = None
    priority: int = 0

    def __post_init__(self):
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if self.timestamp <= 0:
            raise ValueError("Invalid timestamp")

@dataclass(kw_only=True)
class KlineEvent(Event):
    timeframe: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    num_trades: int
    is_closed: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be less than close_time")
        if any(v < 0 for v in [self.open, self.high, self.low, self.close, self.volume]):
            raise ValueError("Price and volume must be non-negative")

@dataclass(kw_only=True)
class OrderBookEvent(Event):
    bids: List[tuple[float, float]]
    asks: List[tuple[float, float]]

    def __post_init__(self):
        super().__post_init__()
        if not (self.bids and self.asks):
            raise ValueError("Bids and asks cannot be empty")

@dataclass(kw_only=True)
class FundingRateEvent(Event):
    funding_rate: float

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.funding_rate, float):
            raise ValueError("Funding rate must be a float")

@dataclass(kw_only=True)
class MarkPriceEvent(Event):
    mark_price: float

    def __post_init__(self):
        super().__post_init__()
        if self.mark_price <= 0:
            raise ValueError("Mark price must be positive")

@dataclass(kw_only=True)
class SignalEvent(Event):
    timeframe: str
    signal: Dict

    def __post_init__(self):
        super().__post_init__()
        if not self.signal:
            raise ValueError("Signal cannot be empty")

@dataclass(kw_only=True)
class OrderEvent(Event):
    order: Union[Order, OCOOrder]

    def __post_init__(self):
        super().__post_init__()
        self.position_side = self.order.position_side

@dataclass
class RiskEvent(Event):
    risk_type: str = "general"

    def __post_init__(self):
        super().__post_init__()
        valid_risk_types = ["margin_ratio", "correlation", "funding_rate", "position_size", "general"]
        if self.risk_type not in valid_risk_types:
            raise ValueError(f"Invalid risk_type: {self.risk_type}")

@dataclass(kw_only=True)
class TradeEvent(Event):
    price: float
    quantity: float
    is_buyer_maker: bool

    def __post_init__(self):
        super().__post_init__()
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("Price and quantity must be positive")

@dataclass(kw_only=True)
class LiquidationEvent(Event):
    side: str
    price: float
    quantity: float

    def __post_init__(self):
        super().__post_init__()
        if self.side not in ["LONG", "SHORT"]:
            raise ValueError("Side must be LONG or SHORT")
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("Price and quantity must be positive")

@dataclass(kw_only=True)
class PositionEvent(Event):
    position: Position
    action: str  # "OPEN", "UPDATE", "CLOSE"

    def __post_init__(self):
        super().__post_init__()
        self.position_side = PositionSide(self.position.side)  # Chuyển đổi chuỗi thành PositionSide enum
        if self.action not in ["OPEN", "UPDATE", "CLOSE"]:
            raise ValueError("Action must be OPEN, UPDATE, or CLOSE")

class EventBus:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.subscribers: Dict[str, List[Dict[str, Any]]] = {}
        self.lock = asyncio.Lock()
        logger.info("Initialized EventBus with enabled events: %s", settings.enabled_events)

    async def subscribe(self, event_type: str, handler: Callable, priority: int = 0, filter_func: Optional[Callable] = None) -> str:
        """Đăng ký handler cho sự kiện với ưu tiên và bộ lọc."""
        async with self.lock:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            handler_id = f"{event_type}_{id(handler)}"
            self.subscribers[event_type].append({
                "handler": handler,
                "priority": priority,
                "filter": filter_func,
                "id": handler_id
            })
            logger.debug("Subscribed handler %s for event %s with priority %d", handler_id, event_type, priority)
            return handler_id

    async def unsubscribe(self, event_type: str, handler_id: str) -> bool:
        """Hủy đăng ký handler."""
        async with self.lock:
            if event_type in self.subscribers:
                initial_len = len(self.subscribers[event_type])
                self.subscribers[event_type] = [
                    sub for sub in self.subscribers[event_type] if sub["id"] != handler_id
                ]
                if len(self.subscribers[event_type]) < initial_len:
                    logger.debug("Unsubscribed handler %s from event %s", handler_id, event_type)
                    return True
                if not self.subscribers[event_type]:
                    del self.subscribers[event_type]
            logger.warning("Handler %s not found for event %s", handler_id, event_type)
            return False

    async def publish(self, event_type: str, event: Event) -> None:
        """Gửi sự kiện đến các subscribers."""
        if event_type not in self.settings.enabled_events:
            logger.debug("Event type %s is disabled, skipping publish", event_type)
            return

        async with self.lock:
            if event_type not in self.subscribers:
                logger.debug("No subscribers for event %s", event_type)
                return

            subscribers = sorted(self.subscribers[event_type], key=lambda x: x["priority"], reverse=True)
            logger.debug("Publishing event %s for %s, timestamp=%d, subscribers=%d",
                         event_type, event.symbol, event.timestamp, len(subscribers))

            for sub in subscribers:
                if not sub["filter"] or sub["filter"](event):
                    try:
                        await sub["handler"](event)
                        logger.debug("Event %s processed by handler %s", event_type, sub["id"])
                    except Exception as e:
                        logger.error("Handler %s failed for event %s: %s", sub["id"], event_type, e)