import asyncio
from typing import Dict, Any, List, Optional
import logging
import uuid
from src.core.settings import Settings
from src.exchange.client import ExchangeClient
from src.trading.orders import Order
from src.trading.enums import OrderStatus
from src.utils.exchange_info import ExchangeInfo

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, exchange: ExchangeClient, settings: Settings, exchange_info: ExchangeInfo):
        self.exchange = exchange
        self.orders: Dict[str, List[Dict]] = {}  # Lưu trữ lệnh theo symbol
        self.backtest_mode = settings.backtest_mode
        self.exchange_info = exchange_info


    async def send_order(self, symbol: str, order: Order) -> Optional[Dict]:
        """Gửi một lệnh đơn lẻ lên sàn hoặc lưu trong backtest."""
        try:
            order.adjust_to_exchange_rules(self.exchange_info.data)
            if not order.validate():
                logger.error("Order validation failed for %s", symbol)
                return None
            if symbol not in self.orders:
                self.orders[symbol] = []
            params = order.to_api_params()
            response = None
            if not self.backtest_mode:
                response = await self.exchange.place_order(**params)
            self.orders[symbol].append(response or self._order_response_for_test_only(order))
            logger.info("Order %s: symbol=%s, order_id=%s", "simulated" if self.backtest_mode else "placed",
                        symbol, response.get("orderId") if response else params.get("newClientOrderId"))
            return response or params
        except Exception as e:
            logger.error("Failed to %s order for %s: %s", "simulate" if self.backtest_mode else "place",
                         symbol, e, exc_info=True)
            return None

    async def place_multiple_orders(self, orders: List[Order]) -> List[Dict]:
        """Đặt hoặc mô phỏng nhiều lệnh cùng lúc."""
        try:
            adjusted_orders = []
            for order in orders:
                order.adjust_to_exchange_rules(self.exchange_info if not self.backtest_mode else {})
                if not order.validate():
                    logger.error("Order validation failed for %s", order.symbol)
                    continue
                adjusted_orders.append(order.to_api_params())

            if not adjusted_orders:
                logger.error("No valid orders to process")
                return []

            response = []
            if not self.backtest_mode:
                response = await self.exchange.place_batch_orders(adjusted_orders)
            else:
                response = adjusted_orders  # Trong backtest, trả về params như phản hồi

            for order, resp in zip(orders, response):
                if self.backtest_mode or "orderId" in resp:
                    if order.symbol not in self.orders:
                        self.orders[order.symbol] = []
                    self.orders[order.symbol].append(resp)
                    logger.info("Batch order %s: symbol=%s, order_id=%s",
                                "simulated" if self.backtest_mode else "placed",
                                order.symbol, resp.get("orderId") or resp.get("newClientOrderId"))
                else:
                    logger.error("Failed to %s batch order for %s: %s",
                                 "simulate" if self.backtest_mode else "place", order.symbol, resp)
            return response
        except Exception as e:
            logger.error("Failed to %s batch orders: %s",
                         "simulate" if self.backtest_mode else "place", e, exc_info=True)
            return []

    async def modify_order(self, symbol: str, order_id: str, new_quantity: Optional[float] = None,
                          new_price: Optional[float] = None, new_stop_price: Optional[float] = None) -> Dict:
        """Sửa hoặc mô phỏng sửa một lệnh hiện có."""
        try:
            # Kiểm tra lệnh tồn tại
            order = next((o for orders in self.orders.values() for o in orders
                         if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id), None)
            if not order:
                logger.error("Order not found: order_id=%s", order_id)
                return {}

            # Điều chỉnh giá/số lượng mới
            if not self.backtest_mode and self.exchange_info:
                symbol_info = next((s for s in self.exchange_info["symbols"] if s["symbol"] == symbol), None)
                if not symbol_info:
                    logger.error(f"No exchange info for symbol {symbol}")
                    return {}
                tick_size = float(next(f["tickSize"] for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER"))
                step_size = float(next(f["stepSize"] for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE"))
                price_precision = symbol_info["pricePrecision"]
                quantity_precision = symbol_info["quantityPrecision"]

                if new_quantity:
                    new_quantity = round(new_quantity / step_size) * step_size
                    new_quantity = round(new_quantity, quantity_precision)
                if new_price:
                    new_price = round(new_price / tick_size) * tick_size
                    new_price = round(new_price, price_precision)
                if new_stop_price:
                    new_stop_price = round(new_stop_price / tick_size) * tick_size
                    new_stop_price = round(new_stop_price, price_precision)

            response = {}
            if not self.backtest_mode:
                response = await self.exchange.modify_order(symbol, order_id, new_quantity, new_price, new_stop_price)
            else:
                # Trong backtest, mô phỏng sửa đổi bằng cách cập nhật params
                response = order.copy()
                if new_quantity:
                    response["quantity"] = f"{new_quantity:.3f}" if new_quantity else order["quantity"]
                if new_price:
                    response["price"] = f"{new_price:.2f}" if new_price else order.get("price")
                if new_stop_price:
                    response["stopPrice"] = f"{new_stop_price:.2f}" if new_stop_price else order.get("stopPrice")

            # Cập nhật self.orders
            if symbol in self.orders:
                for i, o in enumerate(self.orders[symbol]):
                    if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id:
                        self.orders[symbol][i] = response
                        break
            logger.info("Order %s: symbol=%s, order_id=%s",
                        "simulated modify" if self.backtest_mode else "modified", symbol, order_id)
            return response
        except Exception as e:
            logger.error("Failed to %s order %s for %s: %s",
                         "simulate modify" if self.backtest_mode else "modify",
                         order_id, symbol, e, exc_info=True)
            return {}

    async def modify_multiple_orders(self, symbol: str, modifications: List[Dict[str, Any]]) -> List[Dict]:
        """Sửa hoặc mô phỏng sửa nhiều lệnh cùng lúc."""
        try:
            responses = []
            for mod in modifications:
                response = await self.modify_order(
                    symbol=symbol,
                    order_id=mod.get("order_id"),
                    new_quantity=mod.get("new_quantity"),
                    new_price=mod.get("new_price"),
                    new_stop_price=mod.get("new_stop_price")
                )
                responses.append(response)
            logger.info("%s %d orders for symbol %s",
                        "Simulated modification of" if self.backtest_mode else "Modified",
                        len(responses), symbol)
            return responses
        except Exception as e:
            logger.error("Failed to %s multiple orders for %s: %s",
                         "simulate modify" if self.backtest_mode else "modify",
                         symbol, e, exc_info=True)
            return []

    async def get_order_modify_history(self, symbol: str, order_id: str) -> List[Dict]:
        """Lấy lịch sử sửa đổi của một lệnh (không áp dụng trong backtest)."""
        try:
            if self.backtest_mode:
                logger.warning("Order modify history not available in backtest mode")
                return []
            response = await self.exchange.get_order_modify_history(symbol, order_id)
            logger.info("Retrieved order modify history: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error("Failed to get order modify history for %s, %s: %s",
                         symbol, order_id, e, exc_info=True)
            return []

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """Hủy hoặc mô phỏng hủy một lệnh."""
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.cancel_order(symbol, order_id)
            else:
                # Trong backtest, mô phỏng hủy bằng cách đánh dấu trạng thái
                order = next((o for o in self.orders.get(symbol, [])
                             if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id), None)
                if order:
                    response = order.copy()
                    response["status"] = OrderStatus.CANCELED.value

            if symbol in self.orders:
                self.orders[symbol] = [o for o in self.orders[symbol]
                                     if o.get("orderId") != order_id and o.get("newClientOrderId") != order_id]
            logger.info("Order %s: symbol=%s, order_id=%s",
                        "simulated cancel" if self.backtest_mode else "canceled", symbol, order_id)
            return response
        except Exception as e:
            logger.error("Failed to %s order %s for %s: %s",
                         "simulate cancel" if self.backtest_mode else "cancel",
                         order_id, symbol, e, exc_info=True)
            return {}

    async def cancel_multiple_orders(self, symbol: str, order_ids: List[str]) -> List[Dict]:
        """Hủy hoặc mô phỏng hủy nhiều lệnh cùng lúc."""
        try:
            responses = []
            for order_id in order_ids:
                response = await self.cancel_order(symbol, order_id)
                responses.append(response)
            logger.info("%s %d orders for symbol %s",
                        "Simulated cancellation of" if self.backtest_mode else "Canceled",
                        len(responses), symbol)
            return responses
        except Exception as e:
            logger.error("Failed to %s multiple orders for %s: %s",
                         "simulate cancel" if self.backtest_mode else "cancel",
                         symbol, e, exc_info=True)
            return []

    async def cancel_all_open_orders(self, symbol: str) -> Dict:
        """Hủy hoặc mô phỏng hủy tất cả lệnh đang mở cho một symbol."""
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.cancel_all_open_orders(symbol)
            else:
                # Trong backtest, mô phỏng hủy tất cả lệnh mở
                response = {"symbol": symbol, "status": "CANCELED_ALL"}
                if symbol in self.orders:
                    self.orders[symbol] = [o for o in self.orders[symbol]
                                         if o.get("status") not in [OrderStatus.NEW.value,
                                                                  OrderStatus.PARTIALLY_FILLED.value]]

            if symbol in self.orders:
                self.orders[symbol] = []
            logger.info("All open orders %s for symbol %s",
                        "simulated canceled" if self.backtest_mode else "canceled", symbol)
            return response
        except Exception as e:
            logger.error("Failed to %s all open orders for %s: %s",
                         "simulate cancel" if self.backtest_mode else "cancel",
                         symbol, e, exc_info=True)
            return {}

    async def auto_cancel_all_open_orders(self, symbols: List[str], timeout: float = 3600.0) -> None:
        """Tự động hủy tất cả lệnh đang mở sau một khoảng thời gian."""
        try:
            await asyncio.sleep(timeout)
            for symbol in symbols:
                await self.cancel_all_open_orders(symbol)
            logger.info("Auto-%s all open orders for symbols: %s",
                        "simulated canceled" if self.backtest_mode else "canceled", symbols)
        except Exception as e:
            logger.error("Failed to auto-%s open orders: %s",
                         "simulate cancel" if self.backtest_mode else "cancel", e, exc_info=True)

    async def query_order(self, symbol: str, order_id: str) -> Dict:
        """Truy vấn hoặc mô phỏng truy vấn thông tin một lệnh."""
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.get_order_status(symbol, order_id)
            else:
                # Trong backtest, trả về lệnh từ self.orders
                response = next((o for o in self.orders.get(symbol, [])
                                if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id), {})
            logger.info("Queried order: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error("Failed to query order %s for %s: %s", order_id, symbol, e, exc_info=True)
            return {}

    async def query_all_orders(self, symbol: str, limit: int = 1000) -> List[Dict]:
        """Truy vấn hoặc mô phỏng truy vấn tất cả lệnh cho một symbol."""
        try:
            response = []
            if not self.backtest_mode:
                response = await self.exchange.query_all_orders(symbol, limit)
            else:
                # Trong backtest, trả về tất cả lệnh từ self.orders
                response = self.orders.get(symbol, [])[:limit]
            logger.info("Queried all orders for symbol %s, count=%d", symbol, len(response))
            return response
        except Exception as e:
            logger.error("Failed to query all orders for %s: %s", symbol, e, exc_info=True)
            return []

    async def query_current_all_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Truy vấn hoặc mô phỏng truy vấn tất cả lệnh đang mở."""
        try:
            response = []
            if not self.backtest_mode:
                response = await self.exchange.query_current_all_open_orders(symbol)
            else:
                # Trong backtest, trả về các lệnh có trạng thái NEW hoặc PARTIALLY_FILLED
                if symbol:
                    response = [o for o in self.orders.get(symbol, [])
                               if o.get("status") in [OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value]]
                else:
                    response = [o for orders in self.orders.values() for o in orders
                               if o.get("status") in [OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value]]
            logger.info("Queried current open orders for symbol %s, count=%d", symbol or "all", len(response))
            return response
        except Exception as e:
            logger.error("Failed to query current open orders for %s: %s", symbol or "all", e, exc_info=True)
            return []

    async def query_current_open_order(self, symbol: str, order_id: str) -> Dict:
        """Truy vấn hoặc mô phỏng truy vấn một lệnh đang mở cụ thể."""
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.query_current_open_order(symbol, order_id)
            else:
                # Trong backtest, trả về lệnh nếu đang mở
                order = next((o for o in self.orders.get(symbol, [])
                             if (o.get("orderId") == order_id or o.get("newClientOrderId") == order_id)
                             and o.get("status") in [OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value]), {})
                response = order
            logger.info("Queried current open order: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error("Failed to query current open order %s for %s: %s", order_id, symbol, e, exc_info=True)
            return {}

    async def query_users_force_orders(self, symbol: Optional[str] = None, auto_close_type: Optional[str] = None) -> List[Dict]:
        """Truy vấn hoặc mô phỏng truy vấn các lệnh bị buộc đóng (chỉ áp dụng ngoài backtest)."""
        try:
            if self.backtest_mode:
                logger.warning("Force orders not available in backtest mode")
                return []
            response = await self.exchange.query_users_force_orders(symbol, auto_close_type)
            logger.info("Queried force orders for symbol %s, count=%d", symbol or "all", len(response))
            return response
        except Exception as e:
            logger.error("Failed to query force orders for %s: %s", symbol or "all", e, exc_info=True)
            return []

    @staticmethod
    def _order_response_for_test_only(order: Order) -> Order:
        """ """
        order.executed_qty = order.quantity
        order.order_id = str(uuid.uuid4())
        order.avg_price = order.price
        fee = order.calculate_fee(is_maker=False, maker_fee=0.0002, taker_fee=0.0004)
        order.fee = fee

        return order