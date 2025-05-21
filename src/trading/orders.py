import logging
from dataclasses import dataclass
from typing import Optional, Dict
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce

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
    callback_rate: Optional[float] = None  # For TRAILING_STOP_MARKET
    activation_price: Optional[float] = None  # Optional for TRAILING_STOP_MARKET

    def adjust_to_exchange_rules(self, exchange_info: Dict[str, any]) -> None:
        """Điều chỉnh giá và số lượng theo quy tắc của sàn giao dịch."""
        symbol_info = exchange_info[self.symbol]
        print(symbol_info)
        if not symbol_info:
            logger.error(f"No exchange info found for symbol {self.symbol}")
            raise ValueError(f"No exchange info for {self.symbol}")

        # Lấy thông tin từ PRICE_FILTER và LOT_SIZE
        price_filter = next((f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER"), None)
        lot_size = next((f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE"), None)
        min_notional = next((f for f in symbol_info["filters"] if f["filterType"] == "MIN_NOTIONAL"), None)

        if not price_filter or not lot_size:
            logger.error(f"Missing PRICE_FILTER or LOT_SIZE for {self.symbol}")
            raise ValueError(f"Invalid exchange info for {self.symbol}")

        tick_size = float(price_filter["tickSize"])
        step_size = float(lot_size["stepSize"])
        min_qty = float(lot_size["minQty"])
        max_qty = float(lot_size["maxQty"])
        min_notional_value = float(min_notional["notional"]) if min_notional else 0.0

        # Làm tròn số lượng theo stepSize
        if step_size > 0:
            self.quantity = round(self.quantity / step_size) * step_size
            self.quantity = round(self.quantity, symbol_info["quantityPrecision"])

        # Kiểm tra số lượng
        if self.quantity < min_qty:
            logger.error(f"Quantity {self.quantity} below minQty {min_qty} for {self.symbol}")
            raise ValueError(f"Quantity too low for {self.symbol}")
        if self.quantity > max_qty:
            logger.error(f"Quantity {self.quantity} exceeds maxQty {max_qty} for {self.symbol}")
            raise ValueError(f"Quantity too high for {self.symbol}")

        # Kiểm tra giá trị tối thiểu (MIN_NOTIONAL)
        if self.price and min_notional:
            notional = self.quantity * self.price
            if notional < min_notional_value:
                logger.error(f"Notional value {notional} below minNotional {min_notional_value} for {self.symbol}")
                raise ValueError(f"Notional value too low for {self.symbol}")

        # Làm tròn giá theo tick_size
        if self.price:
            self.price = round(self.price / tick_size) * tick_size
            self.price = round(self.price, symbol_info["pricePrecision"])
        if self.stop_price:
            self.stop_price = round(self.stop_price / tick_size) * tick_size
            self.stop_price = round(self.stop_price, symbol_info["pricePrecision"])

    def calculate_fee(self, is_maker: bool, maker_fee: float, taker_fee: float) -> float:
        """Tính phí giao dịch dựa trên maker/taker."""
        fee_rate = maker_fee if is_maker else taker_fee
        self.fee = self.executed_qty * self.avg_price * fee_rate
        logger.debug(f"Calculated fee: {self.fee} for order {self.order_id}, is_maker={is_maker}")
        return self.fee

    def validate(self) -> bool:
        if self.quantity <= 0:
            logger.error("Invalid order: quantity must be positive")
            return False

        if self.type == OrderType.LIMIT and not self.price:
            logger.error("Invalid LIMIT order: price is required")
            return False

        if self.type in [OrderType.STOP, OrderType.TAKE_PROFIT] and (not self.stop_price or not self.price):
            logger.error("Invalid STOP/TP order: price and stop_price required")
            return False

        if self.type in [OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET] and not self.stop_price:
            logger.error("Invalid STOP_MARKET/TP_MARKET order: stop_price required")
            return False

        if self.type == OrderType.TRAILING_STOP_MARKET and self.callback_rate is None:
            logger.error("Invalid TRAILING_STOP_MARKET: callback_rate required")
            return False

        return True

    def to_api_params(self) -> dict:
        """Chuyển đổi sang định dạng API Binance Futures tùy theo loại lệnh."""
        params = {
            "symbol": self.symbol,
            "side": self.side.value,
            "positionSide": self.position_side.value,
            "type": self.type.value,
            "quantity": f"{self.quantity:.3f}",
            "reduceOnly": "true" if self.reduce_only else None,
            "closePosition": "true" if self.close_position else None,
            "newClientOrderId": self.client_order_id,
        }

        if self.type == OrderType.LIMIT:
            params["price"] = f"{self.price:.2f}"
            params["timeInForce"] = self.time_in_force.value

        elif self.type == OrderType.MARKET:
            pass  # Không cần thêm gì

        elif self.type in [OrderType.STOP, OrderType.TAKE_PROFIT]:
            params["stopPrice"] = f"{self.stop_price:.2f}"
            params["price"] = f"{self.price:.2f}"
            params["timeInForce"] = self.time_in_force.value

        elif self.type in [OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET]:
            params["stopPrice"] = f"{self.stop_price:.2f}"

        elif self.type == OrderType.TRAILING_STOP_MARKET:
            if self.callback_rate is None:
                raise ValueError("callback_rate is required for TRAILING_STOP_MARKET")
            params["callbackRate"] = f"{self.callback_rate:.2f}"
            if self.activation_price:
                params["activationPrice"] = f"{self.activation_price:.2f}"

        return {k: v for k, v in params.items() if v is not None}

class OCOOrder:
    pass