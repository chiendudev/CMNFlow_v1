from typing import Callable, Dict, List, Any, Optional
from dataclasses import dataclass
import asyncio
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Các lớp sự kiện cụ thể
@dataclass
class TradeEvent:
    """Sự kiện giao dịch (aggTrade hoặc trade) từ WebSocket hoặc API."""
    symbol: str
    data: dict  # Dữ liệu thô từ Binance (id, price, qty, timestamp, is_maker, v.v.)

@dataclass
class OrderBookEvent:
    """Sự kiện cập nhật order book từ WebSocket hoặc API."""
    symbol: str
    bids: List[tuple[float, float]]  # [price, quantity]
    asks: List[tuple[float, float]]  # [price, quantity]
    timestamp: int

@dataclass
class FundingRateEvent:
    """Sự kiện lãi suất funding từ WebSocket hoặc API."""
    symbol: str
    funding_rate: float
    funding_time: int

@dataclass
class MarkPriceEvent:
    """Sự kiện giá mark từ WebSocket hoặc API."""
    symbol: str
    mark_price: float
    timestamp: int

@dataclass
class OpenInterestEvent:
    """Sự kiện open interest từ API."""
    symbol: str
    open_interest: float
    timestamp: int

@dataclass
class SignalEvent:
    """Sự kiện tín hiệu giao dịch từ SignalGenerator."""
    symbol: str
    timeframe: str
    signal: dict  # {type: buy/sell, entry, stop_loss, take_profit, v.v.}

class EventBus:
    def __init__(self):
        """Khởi tạo EventBus để quản lý đăng ký và phát hành sự kiện."""
        self._handlers: Dict[str, List[Callable[[Any], None]]] = {}
        self._lock = asyncio.Lock()  # Đồng bộ truy cập handlers

    def subscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """
        Đăng ký handler cho một loại sự kiện.

        Args:
            event_type: Loại sự kiện (trade, order_book, signal, v.v.).
            handler: Hàm xử lý sự kiện (có thể là async).
        """
        with asyncio.get_event_loop().get_running_loop():
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
            logger.debug("Subscribed handler for event type: %s", event_type)

    def unsubscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """
        Hủy đăng ký handler cho một loại sự kiện.

        Args:
            event_type: Loại sự kiện.
            handler: Hàm xử lý cần hủy.
        """
        with asyncio.get_event_loop().get_running_loop():
            if event_type in self._handlers:
                self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]
                logger.debug("Unsubscribed handler for event type: %s", event_type)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def publish(self, event_type: str, event: Any) -> None:
        """
        Phát hành một sự kiện đến tất cả handlers đã đăng ký.

        Args:
            event_type: Loại sự kiện.
            event: Đối tượng sự kiện (TradeEvent, SignalEvent, v.v.).
        """
        async with self._lock:
            if event_type not in self._handlers:
                logger.debug("No handlers for event type: %s", event_type)
                return

            for handler in self._handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                    logger.debug("Processed event type %s for %s", event_type, getattr(event, 'symbol', 'unknown'))
                except Exception as e:
                    logger.error("Failed to process event %s: %s", event_type, e)
                    raise  # Retry nếu cần

    async def clear(self) -> None:
        """Xóa tất cả handlers, dùng trong cleanup hoặc test."""
        async with self._lock:
            self._handlers.clear()
            logger.info("Cleared all event handlers")