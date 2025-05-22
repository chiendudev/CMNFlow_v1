import logging
from dataclasses import dataclass
from typing import Optional
from src.trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce
from src.utils.symbol_info import SymbolInfo

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
    callback_rate: Optional[float] = None
    activation_price: Optional[float] = None

    def adjust_to_exchange_rules(self, symbol_info: SymbolInfo, mark_price: Optional[float] = None) -> None:
        """Điều chỉnh giá và số lượng theo quy tắc của Binance Futures."""
        if not symbol_info:
            logger.error(f"No SymbolInfo found for symbol {self.symbol}")
            raise ValueError(f"No SymbolInfo for {self.symbol}")

        tick_size = float(symbol_info.tick_size) if symbol_info.tick_size else 0.0
        step_size = float(symbol_info.step_size) if symbol_info.step_size else 0.0
        min_qty = symbol_info.min_qty
        max_qty = symbol_info.max_qty
        min_notional = symbol_info.min_notional
        max_notional = symbol_info.max_notional_value
        min_price = symbol_info.min_price
        max_price = symbol_info.max_price
        price_precision = symbol_info.price_precision
        quantity_precision = symbol_info.quantity_precision
        multiplier_down = symbol_info.multiplier_down
        multiplier_up = symbol_info.multiplier_up

        # Kiểm tra order_type
        if self.type.value not in symbol_info.order_types:
            logger.error(f"Order type {self.type.value} not supported for {self.symbol}")
            raise ValueError(f"Unsupported order type {self.type.value}")

        # Kiểm tra time_in_force
        if self.time_in_force.value not in symbol_info.time_in_force:
            logger.error(f"Time in force {self.time_in_force.value} not supported for {self.symbol}")
            raise ValueError(f"Unsupported time_in_force {self.time_in_force.value}")

        # Làm tròn số lượng theo step_size
        if step_size > 0:
            self.quantity = round(self.quantity / step_size) * step_size
            self.quantity = round(self.quantity, quantity_precision)
            if self.executed_qty > 0:
                self.executed_qty = round(self.executed_qty / step_size) * step_size
                self.executed_qty = round(self.executed_qty, quantity_precision)

        # Kiểm tra số lượng
        if self.quantity < min_qty:
            logger.error(f"Quantity {self.quantity} below min_qty {min_qty} for {self.symbol}")
            raise ValueError(f"Quantity too low for {self.symbol}")
        if self.quantity > max_qty:
            logger.error(f"Quantity {self.quantity} exceeds max_qty {max_qty} for {self.symbol}")
            raise ValueError(f"Quantity too high for {self.symbol}")

        # Làm tròn giá theo tick_size
        if self.price and tick_size > 0:
            self.price = round(self.price / tick_size) * tick_size
            self.price = round(self.price, price_precision)
        if self.stop_price and tick_size > 0:
            self.stop_price = round(self.stop_price / tick_size) * tick_size
            self.stop_price = round(self.stop_price, price_precision)
        if self.avg_price and tick_size > 0:
            self.avg_price = round(self.avg_price / tick_size) * tick_size
            self.avg_price = round(self.avg_price, price_precision)

        # Kiểm tra giá trong phạm vi min_price, max_price
        if self.price and (min_price > 0 or max_price > 0):
            if min_price > 0 and self.price < min_price:
                logger.error(f"Price {self.price} below min_price {min_price} for {self.symbol}")
                raise ValueError(f"Price too low for {self.symbol}")
            if 0 < max_price < self.price:
                logger.error(f"Price {self.price} exceeds max_price {max_price} for {self.symbol}")
                raise ValueError(f"Price too high for {self.symbol}")

        if self.stop_price and (min_price > 0 or max_price > 0):
            if min_price > 0 and self.stop_price < min_price:
                logger.error(f"Stop price {self.stop_price} below min_price {min_price} for {self.symbol}")
                raise ValueError(f"Stop price too low for {self.symbol}")
            if 0 < max_price < self.stop_price:
                logger.error(f"Stop price {self.stop_price} exceeds max_price {max_price} for {self.symbol}")
                raise ValueError(f"Stop price too high for {self.symbol}")

        # Kiểm tra MIN_NOTIONAL và MAX_NOTIONAL
        if self.price:
            notional = self.quantity * self.price
            if notional < min_notional:
                logger.error(f"Notional value {notional} below min_notional {min_notional} for {self.symbol}")
                raise ValueError(f"Notional value too low for {self.symbol}")
            if 0 < max_notional < notional:
                logger.error(f"Notional value {notional} exceeds max_notional {max_notional} for {self.symbol}")
                raise ValueError(f"Notional value too high for {self.symbol}")

        # Kiểm tra PERCENT_PRICE
        if self.price and mark_price and multiplier_down > 0 and multiplier_up > 0:
            min_allowed_price = mark_price * multiplier_down
            max_allowed_price = mark_price * multiplier_up
            min_allowed_price = round(min_allowed_price, symbol_info.multiplier_decimal)
            max_allowed_price = round(max_allowed_price, symbol_info.multiplier_decimal)
            if not (min_allowed_price <= self.price <= max_allowed_price):
                logger.error(f"Price {self.price} outside PERCENT_PRICE range [{min_allowed_price}, {max_allowed_price}] for {self.symbol}")
                raise ValueError(f"Price outside allowed PERCENT_PRICE range")

        # Kiểm tra đòn bẩy dựa trên brackets
        if symbol_info.brackets and self.price:
            notional = self.quantity * self.price
            for bracket in symbol_info.brackets:
                if bracket.notional_floor <= notional <= bracket.notional_cap:
                    if symbol_info.leverage > bracket.initial_leverage:
                        logger.error(f"Leverage {symbol_info.leverage} exceeds max leverage {bracket.initial_leverage} for notional {notional}")
                        raise ValueError(f"Invalid leverage for notional value {notional}")
                    break
            else:
                logger.error(f"Notional value {notional} does not fit any leverage bracket for {self.symbol}")
                raise ValueError(f"Notional value outside leverage brackets")

    def calculate_fee(self, is_maker: bool, symbol_info: SymbolInfo) -> float:
        """Tính phí giao dịch dựa trên maker/taker từ SymbolInfo."""
        fee_rate = symbol_info.maker_commission_rate if is_maker else symbol_info.taker_commission_rate
        self.fee = self.executed_qty * self.avg_price * fee_rate
        logger.debug(f"Calculated fee: {self.fee} for order {self.order_id}, is_maker={is_maker}, fee_rate={fee_rate}")
        return self.fee

    def validate(self) -> bool:
        """Kiểm tra tính hợp lệ của lệnh theo quy tắc Binance Futures."""
        if self.quantity <= 0:
            logger.error("Invalid order: quantity must be positive")
            return False

        if self.type == OrderType.LIMIT and not self.price:
            logger.error("Invalid LIMIT order: price is required")
            return False

        if self.type in [OrderType.STOP, OrderType.TAKE_PROFIT] and (not self.stop_price or not self.price):
            logger.error("Invalid STOP/TAKE_PROFIT order: price and stop_price required")
            return False

        if self.type in [OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET] and not self.stop_price:
            logger.error("Invalid STOP_MARKET/TAKE_PROFIT_MARKET order: stop_price required")
            return False

        if self.type == OrderType.TRAILING_STOP_MARKET and self.callback_rate is None:
            logger.error("Invalid TRAILING_STOP_MARKET: callback_rate required")
            return False

        if self.type == OrderType.MARKET and self.price:
            logger.error("Invalid MARKET order: price should not be specified")
            return False

        if self.reduce_only and self.close_position:
            logger.error("Invalid order: reduce_only and close_position cannot both be True")
            return False

        if self.position_side == PositionSide.BOTH and self.type in [
            OrderType.STOP,
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.TRAILING_STOP_MARKET
        ]:
            logger.error(f"Invalid position_side BOTH for order type {self.type}")
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