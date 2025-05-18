from typing import Callable, Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import asyncio
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

# Khởi tạo logger
logger = logging.getLogger(__name__)


# Các lớp sự kiện
@dataclass
class TradeEvent:
    """Sự kiện giao dịch (aggTrade hoặc trade) từ WebSocket hoặc API."""
    symbol: str
    data: dict  # Dữ liệu thô: id, price, qty, timestamp, is_maker, v.v.


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


@dataclass
class LiquidationEvent:
    """Sự kiện thanh lý từ WebSocket (@forceOrder) hoặc API."""
    symbol: str
    side: str  # BUY/SELL
    price: float
    quantity: float
    timestamp: int


@dataclass
class KlineEvent:
    """Sự kiện cập nhật nến từ WebSocket (@kline_<interval>)."""
    symbol: str
    timeframe: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    num_trades: int
    is_closed: bool


class EventBus:
    def __init__(self):
        """Khởi tạo EventBus để quản lý đăng ký và phát hành sự kiện với priority và filtering."""
        self._handlers: Dict[str, List[Tuple[int, Callable[[Any], None], Optional[Callable[[Any], bool]]]]] = {}
        self._lock = asyncio.Lock()  # Đồng bộ truy cập handlers
        self._default_priority = 10  # Ưu tiên mặc định

    def subscribe(self, event_type: str, handler: Callable[[Any], None],
                  priority: int = 10, filter_func: Optional[Callable[[Any], bool]] = None) -> None:
        """
        Đăng ký handler cho một loại sự kiện với ưu tiên và bộ lọc.

        Args:
            event_type: Loại sự kiện (trade, signal, liquidation, v.v.).
            handler: Hàm xử lý sự kiện (có thể là async).
            priority: Mức ưu tiên (số nhỏ hơn = ưu tiên cao hơn).
            filter_func: Hàm lọc, trả về True nếu sự kiện được xử lý.
        """
        # Sử dụng asyncio.get_event_loop() làm fallback
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append((priority, handler, filter_func))
        # Sắp xếp handlers theo priority
        self._handlers[event_type].sort(key=lambda x: x[0])
        logger.debug("Subscribed handler for event type: %s, priority: %d", event_type, priority)

    def unsubscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """
        Hủy đăng ký handler cho một loại sự kiện.

        Args:
            event_type: Loại sự kiện.
            handler: Hàm xử lý cần hủy.
        """
        # Sử dụng asyncio.get_event_loop() làm fallback
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h[1] != handler]
            logger.debug("Unsubscribed handler for event type: %s", event_type)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def publish(self, event_type: str, event: Any) -> None:
        """
        Phát hành một sự kiện đến tất cả handlers đã đăng ký, theo thứ tự ưu tiên và bộ lọc.

        Args:
            event_type: Loại sự kiện.
            event: Đối tượng sự kiện (TradeEvent, SignalEvent, v.v.).
        """
        async with self._lock:
            if event_type not in self._handlers:
                logger.debug("No handlers for event type: %s", event_type)
                return

            for priority, handler, filter_func in self._handlers[event_type]:
                try:
                    # Kiểm tra bộ lọc
                    if filter_func and not filter_func(event):
                        logger.debug("Event %s filtered out for handler with priority %d", event_type, priority)
                        continue

                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                    logger.debug("Processed event type %s for %s, priority %d",
                                 event_type, getattr(event, 'symbol', 'unknown'), priority)
                except Exception as e:
                    logger.error("Failed to process event %s with priority %d: %s", event_type, priority, e)
                    raise  # Retry nếu cần

    async def clear(self) -> None:
        """Xóa tất cả handlers, dùng trong cleanup hoặc test."""
        async with self._lock:
            self._handlers.clear()
            logger.info("Cleared all event handlers")