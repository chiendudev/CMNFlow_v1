from dataclasses import dataclass
from typing import List, Optional
from trading.enums import OrderSide, PositionSide, OrderType, OrderStatus
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class NewOrder:
    symbol: str
    side: OrderSide
    position_side: PositionSide
    quantity: float
    price: float
    status: OrderStatus
    fee: float = 0.0
    executed_qty: float = 0.0
    avg_price: float = 0.0
    reduce_only: bool = False

class StopOrder:
    def __init__(self, symbol: str, position_side: PositionSide, stop_price: float, quantity: float, is_take_profit: bool, side: OrderSide):
        self.symbol = symbol
        self.position_side = position_side
        self.stop_price = stop_price
        self.quantity = quantity
        self.is_take_profit = is_take_profit
        self.side = side

    def should_trigger(self, price: float, position_side: PositionSide) -> bool:
        if self.position_side != position_side:
            return False
        if self.is_take_profit:
            return (price >= self.stop_price and self.side == OrderSide.SELL) or (price <= self.stop_price and self.side == OrderSide.BUY)
        return (price <= self.stop_price and self.side == OrderSide.SELL) or (price >= self.stop_price and self.side == OrderSide.BUY)

class TrailingStopOrder(StopOrder):
    def __init__(self, symbol: str, position_side: PositionSide, stop_price: float, quantity: float, is_take_profit: bool, side: OrderSide, delta: float, delta_type: str, callback_rate: float):
        super().__init__(symbol, position_side, stop_price, quantity, is_take_profit, side)
        self.delta = delta
        self.delta_type = delta_type
        self.callback_rate = callback_rate
        self.last_trigger_price = stop_price

    def update(self, price: float, position_side: PositionSide):
        if self.position_side != position_side:
            return
        if self.delta_type == 'percentage':
            delta_price = price * self.delta / 100
        else:
            delta_price = self.delta
        if self.side == OrderSide.SELL:
            if price > self.last_trigger_price:
                self.last_trigger_price = price
                self.stop_price = max(self.stop_price, price - delta_price * (1 + self.callback_rate))
        else:
            if price < self.last_trigger_price:
                self.last_trigger_price = price
                self.stop_price = min(self.stop_price, price + delta_price * (1 + self.callback_rate))

class StopOrderManager:
    def __init__(self, exchange_client):
        self.exchange_client = exchange_client
        self.stop_orders: List[StopOrder] = []

    async def check_stop_orders(self, position, mark_price: float):
        if not self.stop_orders or position.position_amt == 0:
            return
        price_precision = self.exchange_client.get_price_precision(position.symbol)
        truncated_price = round(mark_price - (mark_price % price_precision), 8)
        for stop_order in self.stop_orders[:]:
            stop_order.update(truncated_price, position.position_side) if isinstance(stop_order, TrailingStopOrder) else None
            if stop_order.should_trigger(truncated_price, position.position_side):
                logger.info("Kích hoạt %s%s: Stop Price=%.2f, Qty=%.4f",
                            "Trailing " if isinstance(stop_order, TrailingStopOrder) else "",
                            "TP" if stop_order.is_take_profit else "SL",
                            stop_order.stop_price, stop_order.quantity)
                order = NewOrder(
                    symbol=position.symbol,
                    side=stop_order.side,
                    position_side=stop_order.position_side,
                    quantity=stop_order.quantity,
                    price=stop_order.stop_price,
                    status=OrderStatus.FILLED,
                    fee=round(stop_order.quantity * stop_order.stop_price * self.exchange_client.get_commission_rate(position.symbol), 2),
                    executed_qty=stop_order.quantity,
                    avg_price=stop_order.stop_price,
                    reduce_only=True
                )
                await position.portfolio_manager.process_new_order(order)
                self.stop_orders.remove(stop_order)

    def display_stop_orders(self, symbol: str, position_side: PositionSide):
        if not self.stop_orders:
            logger.info("Không có SL/TP cho %s - %s", symbol, position_side)
            return
        total_qty = sum(so.quantity for so in self.stop_orders)
        logger.info("SL/TP cho %s - %s (Tổng khối lượng: %.4f)", symbol, position_side, total_qty)
        logger.info("Biểu đồ phân bổ (Pie Chart giả lập):")
        for so in self.stop_orders:
            order_type = "Trailing TP" if so.is_take_profit and isinstance(so, TrailingStopOrder) else \
                        "Trailing SL" if not so.is_take_profit and isinstance(so, TrailingStopOrder) else \
                        "TP" if so.is_take_profit else "SL"
            percentage = (so.quantity / total_qty * 100) if total_qty > 0 else 0
            delta_info = f", Trailing Delta={so.delta:.2f}, Callback Rate={so.callback_rate:.2%}" if isinstance(so, TrailingStopOrder) else ""
            logger.info("- %s: Stop Price=%.2f, Qty=%.4f (%.2f%%)%s",
                        order_type, so.stop_price, so.quantity, percentage, delta_info)