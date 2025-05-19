from dataclasses import dataclass
from typing import Optional
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce
import logging

logger = logging.getLogger(__name__)

@dataclass
class Order:
    symbol: str
    side: OrderSide
    position_side: PositionSide
    type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: bool = False
    close_position: bool = False
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.NEW
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    fee: float = 0.0
    executed_qty: float = 0.0
    avg_price: float = 0.0

    def calculate_fee(self, is_maker: bool, maker_fee: float, taker_fee: float) -> float:
        """Tính phí giao dịch dựa trên maker/taker."""
        fee_rate = maker_fee if is_maker else taker_fee
        self.fee = self.executed_qty * self.avg_price * fee_rate
        return self.fee

    def validate(self) -> bool:
        """Kiểm tra tính hợp lệ của lệnh."""
        if self.quantity <= 0:
            logger.error("Invalid order: quantity must be positive")
            return False
        if self.type in [OrderType.LIMIT, OrderType.STOP_LIMIT] and not self.price:
            logger.error("Invalid order: price required for LIMIT/STOP_LIMIT")
            return False
        if self.type in [OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET, OrderType.STOP_LIMIT] and not self.stop_price:
            logger.error("Invalid order: stop_price required for STOP/TAKE_PROFIT")
            return False
        return True

    def to_api_params(self) -> dict:
        """Chuyển đổi sang định dạng API Binance."""
        params = {
            "symbol": self.symbol,
            "side": self.side.value,
            "positionSide": self.position_side.value,
            "type": self.type.value,
            "quantity": f"{self.quantity:.3f}",
            "reduceOnly": "true" if self.reduce_only else "false",
            "closePosition": "true" if self.close_position else "false",
            "timeInForce": self.time_in_force.value,
            "newClientOrderId": self.client_order_id,
        }
        if self.price:
            params["price"] = f"{self.price:.2f}"
        if self.stop_price:
            params["stopPrice"] = f"{self.stop_price:.2f}"
        return {k: v for k, v in params.items() if v is not None}

@dataclass
class OCOOrder:
    symbol: str
    side: OrderSide
    position_side: PositionSide
    quantity: float
    price: float  # Giá LIMIT
    stop_price: float  # Giá STOP_MARKET
    stop_limit_price: Optional[float] = None  # Giá LIMIT cho STOP (nếu STOP_LIMIT)
    stop_limit_time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    list_client_order_id: Optional[str] = None
    limit_client_order_id: Optional[str] = None
    stop_client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    order_list_id: Optional[str] = None
    fee: float = 0.0

    def validate(self) -> bool:
        """Kiểm tra tính hợp lệ của OCO order."""
        if self.quantity <= 0:
            logger.error("Invalid OCO order: quantity must be positive")
            return False
        if self.price <= 0 or self.stop_price <= 0:
            logger.error("Invalid OCO order: price and stop_price must be positive")
            return False
        if self.side == OrderSide.BUY and self.stop_price >= self.price:
            logger.error("Invalid OCO order: for BUY, stop_price must be < price")
            return False
        if self.side == OrderSide.SELL and self.stop_price <= self.price:
            logger.error("Invalid OCO order: for SELL, stop_price must be > price")
            return False
        return True

    def to_api_params(self) -> dict:
        """Chuyển đổi sang định dạng API Binance OCO."""
        params = {
            "symbol": self.symbol,
            "side": self.side.value,
            "positionSide": self.position_side.value,
            "quantity": f"{self.quantity:.3f}",
            "price": f"{self.price:.2f}",
            "stopPrice": f"{self.stop_price:.2f}",
            "stopLimitTimeInForce": self.stop_limit_time_in_force.value,
            "reduceOnly": "true" if self.reduce_only else "false",
            "listClientOrderId": self.list_client_order_id,
            "limitClientOrderId": self.limit_client_order_id,
            "stopClientOrderId": self.stop_client_order_id,
        }
        if self.stop_limit_price:
            params["stopLimitPrice"] = f"{self.stop_limit_price:.2f}"
        return {k: v for k, v in params.items() if v is not None}