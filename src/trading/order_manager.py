import asyncio
from typing import Dict, Any, List, Optional
import logging
import uuid
from src.core.settings import Settings
from src.exchange.client import ExchangeClient
from src.trading.orders import Order
from src.trading.enums import OrderStatus, OrderSide, PositionSide, OrderType
from src.utils.exchange_info import ExchangeInfo
from src.trading.portfolio import Portfolio
from src.utils.user_data_api import UserDataApi
from src.Account.account_info import AccountInfo
from src.utils.symbol_info import SymbolInfo
from src.trading.risk.risk import RiskManager
from src.trading.trend_analyzer import TrendAnalyzer

logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(
        self,
        exchange: ExchangeClient,
        settings: Settings,
        exchange_info: ExchangeInfo,
        portfolio: Portfolio,
        account: AccountInfo,
        user_data: UserDataApi,
        risk_manager: Optional[RiskManager] = None,
        trend_analyzer: Optional[TrendAnalyzer] = None,
        symbol_info_map: Optional[Dict[str, SymbolInfo]] = None,
    ):
        """
        Khởi tạo OrderManager để quản lý lệnh giao dịch trên Binance Futures.

        Args:
            exchange: Đối tượng ExchangeClient để gọi API.
            settings: Cấu hình hệ thống.
            exchange_info: Thông tin sàn giao dịch.
            portfolio: Danh mục đầu tư.
            account: Thông tin tài khoản.
            user_data: API dữ liệu người dùng.
            risk_manager: Đối tượng RiskManager để kiểm tra rủi ro.
            trend_analyzer: Đối tượng TrendAnalyzer để phân tích xu hướng.
            symbol_info_map: Từ điển ánh xạ symbol tới SymbolInfo.
        """
        self.exchange = exchange
        self.settings = settings
        self.exchange_info = exchange_info
        self.portfolio = portfolio
        self.account = account
        self.user_data = user_data
        self.risk_manager = risk_manager
        self.trend_analyzer = trend_analyzer
        self.symbol_info_map = symbol_info_map or {}
        self.backtest_mode = settings.backtest_mode
        self.orders: Dict[str, Dict[str, List[Dict]]] = {}  # Lưu trữ lệnh theo symbol và trạng thái

    def create_order(
        self,
        symbol: str,
        qty: float,
        order_side: OrderSide,
        position_side: PositionSide,
        order_type: OrderType,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Optional[Order]:
        """
        Tạo một lệnh giao dịch mới.

        Args:
            symbol: Cặp giao dịch.
            qty: Số lượng.
            order_side: Loại lệnh (BUY/SELL).
            position_side: Loại vị thế (LONG/SHORT/BOTH).
            order_type: Loại lệnh (MARKET/LIMIT/STOP).
            price: Giá đặt lệnh (cho LIMIT).
            stop_price: Giá dừng (cho STOP).

        Returns:
            Đối tượng Order hoặc None nếu không hợp lệ.
        """
        try:
            symbol_info = self._get_symbol_info(symbol)
            if not symbol_info:
                logger.error(f"SymbolInfo không tồn tại cho {symbol}")
                return None

            # Điều chỉnh số lượng và giá theo SymbolInfo
            qty = self._adjust_quantity(qty, symbol_info)
            if price:
                price = self._adjust_price(price, symbol_info)
            if stop_price:
                stop_price = self._adjust_price(stop_price, symbol_info)

            # Tạo đối tượng Order
            order = Order(
                symbol=symbol,
                side=order_side,
                position_side=position_side,
                type=order_type,
                quantity=qty,
                price=price,
                stop_price=stop_price,
            )

            # Kiểm tra rủi ro
            if self.risk_manager:
                signal = {"size": qty * (price or self._get_current_price(symbol))}
                risk_events = self.risk_manager.check_risk(symbol, order_side.name, signal)
                if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                    logger.error(f"Rủi ro cao khi tạo lệnh: {', '.join(e.message for e in risk_events)}")
                    return None

            # Kiểm tra xu hướng
            if self.trend_analyzer:
                trend_data = self.trend_analyzer.for_risk_manager(symbol, "15m")
                if not trend_data["is_trending"]:
                    logger.warning(f"Không tạo lệnh do xu hướng yếu cho {symbol}")
                    return None

            return order
        except Exception as e:
            logger.error(f"Lỗi khi tạo lệnh cho {symbol}: {str(e)}")
            return None

    async def send_order(self, symbol: str, order: Order) -> Optional[Dict]:
        """
        Gửi một lệnh đơn lẻ lên sàn hoặc lưu trong backtest.

        Args:
            symbol: Cặp giao dịch.
            order: Lệnh giao dịch.

        Returns:
            Phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            symbol_info = self._get_symbol_info(symbol)
            if not symbol_info:
                raise ValueError(f"SymbolInfo không tồn tại cho {symbol}")

            # Kiểm tra số dư khả dụng
            if not self._check_balance(order, symbol_info):
                raise ValueError(f"Số dư không đủ để đặt lệnh cho {symbol}")

            # Kiểm tra rủi ro
            if self.risk_manager:
                signal = {"size": order.quantity * (order.price or self._get_current_price(symbol))}
                risk_events = self.risk_manager.check_risk(symbol, order.side.name, signal)
                if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                    raise ValueError(f"Rủi ro cao: {', '.join(e.message for e in risk_events)}")

            # Kiểm tra xu hướng
            if self.trend_analyzer:
                trend_data = self.trend_analyzer.for_risk_manager(symbol, "15m")
                if not trend_data["is_trending"]:
                    logger.warning(f"Không gửi lệnh do xu hướng yếu cho {symbol}")
                    return None

            # Điều chỉnh lệnh theo quy tắc sàn
            order.adjust_to_exchange_rules(symbol_info)
            if not order.validate():
                logger.error(f"Order validation failed for {symbol}")
                return None

            # Khởi tạo danh sách lệnh nếu cần
            if symbol not in self.orders:
                self.orders[symbol] = {
                    "NEW": [],
                    "FILLED": [],
                    "CANCELED": [],
                    "PARTIALLY_FILLED": [],
                }

            params = order.to_api_params()
            response = None
            if not self.backtest_mode:
                response = await self.exchange.place_order(**params)
            else:
                response = await self._order_response_for_test_only(order)
                self.portfolio.apply_order(response)

            # Lưu lệnh theo trạng thái
            status = response.get("status", OrderStatus.FILLED.value)
            self.orders[symbol][status].append(response)
            logger.info(
                "Order %s: symbol=%s, order_id=%s",
                "simulated" if self.backtest_mode else "placed",
                symbol,
                response.get("orderId") or params.get("newClientOrderId"),
            )

            # Cập nhật Portfolio và AccountInfo
            self.portfolio.apply_order(order)
            if self.account:
                await self.account.initial()  # Đồng bộ dữ liệu tài khoản
                self.portfolio._sync_from_account_info()

            return response
        except Exception as e:
            logger.error(
                "Failed to %s order for %s: %s",
                "simulate" if self.backtest_mode else "place",
                symbol,
                str(e),
                exc_info=True,
            )
            return None

    async def place_multiple_orders(self, orders: List[Order]) -> List[Dict]:
        """
        Đặt hoặc mô phỏng nhiều lệnh cùng lúc.

        Args:
            orders: Danh sách lệnh giao dịch.

        Returns:
            Danh sách phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            adjusted_orders = []
            for order in orders:
                symbol_info = self._get_symbol_info(order.symbol)
                if not symbol_info:
                    logger.error(f"SymbolInfo không tồn tại cho {order.symbol}")
                    continue

                # Kiểm tra số dư
                if not self._check_balance(order, symbol_info):
                    logger.error(f"Số dư không đủ để đặt lệnh cho {order.symbol}")
                    continue

                # Kiểm tra rủi ro
                if self.risk_manager:
                    signal = {"size": order.quantity * (order.price or self._get_current_price(order.symbol))}
                    risk_events = self.risk_manager.check_risk(order.symbol, order.side.name, signal)
                    if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                        logger.error(f"Rủi ro cao: {', '.join(e.message for e in risk_events)}")
                        continue

                # Kiểm tra xu hướng
                if self.trend_analyzer:
                    trend_data = self.trend_analyzer.for_risk_manager(order.symbol, "15m")
                    if not trend_data["is_trending"]:
                        logger.warning(f"Không gửi lệnh do xu hướng yếu cho {order.symbol}")
                        continue

                order.adjust_to_exchange_rules(symbol_info)
                if not order.validate():
                    logger.error(f"Order validation failed for {order.symbol}")
                    continue
                adjusted_orders.append(order)

            if not adjusted_orders:
                logger.error("No valid orders to process")
                return []

            response = []
            if not self.backtest_mode:
                response = await self.exchange.place_batch_orders([o.to_api_params() for o in adjusted_orders])
            else:
                response = [await self._order_response_for_test_only(o) for o in adjusted_orders]

            for order, resp in zip(adjusted_orders, response):
                if self.backtest_mode or "orderId" in resp:
                    if order.symbol not in self.orders:
                        self.orders[order.symbol] = {
                            "NEW": [],
                            "FILLED": [],
                            "CANCELED": [],
                            "PARTIALLY_FILLED": [],
                        }
                    status = resp.get("status", OrderStatus.FILLED.value)
                    self.orders[order.symbol][status].append(resp)
                    logger.info(
                        "Batch order %s: symbol=%s, order_id=%s",
                        "simulated" if self.backtest_mode else "placed",
                        order.symbol,
                        resp.get("orderId") or resp.get("newClientOrderId"),
                    )
                    self.portfolio.apply_order(order)
                else:
                    logger.error(
                        "Failed to %s batch order for %s: %s",
                        "simulate" if self.backtest_mode else "place",
                        order.symbol,
                        resp,
                    )

            # Đồng bộ AccountInfo
            if self.account:
                await self.account.initial()
                self.portfolio._sync_from_account_info()

            return response
        except Exception as e:
            logger.error(
                "Failed to %s batch orders: %s",
                "simulate" if self.backtest_mode else "place",
                str(e),
                exc_info=True,
            )
            return []

    async def modify_order(
        self,
        symbol: str,
        order_id: str,
        new_quantity: Optional[float] = None,
        new_price: Optional[float] = None,
        new_stop_price: Optional[float] = None,
    ) -> Dict:
        """
        Sửa hoặc mô phỏng sửa một lệnh hiện có.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.
            new_quantity: Số lượng mới.
            new_price: Giá mới.
            new_stop_price: Giá dừng mới.

        Returns:
            Phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            symbol_info = self._get_symbol_info(symbol)
            if not symbol_info:
                raise ValueError(f"SymbolInfo không tồn tại cho {symbol}")

            # Kiểm tra lệnh tồn tại
            order = self._find_order(symbol, order_id)
            if not order:
                logger.error(f"Order not found: order_id={order_id}")
                return {}

            # Kiểm tra rủi ro khi sửa lệnh
            if self.risk_manager:
                signal = {
                    "size": (new_quantity or float(order.get("quantity", 0))) * (
                        new_price or float(order.get("price", self._get_current_price(symbol)))
                    )
                }
                risk_events = self.risk_manager.check_risk(symbol, order.get("side"), signal)
                if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                    raise ValueError(f"Rủi ro cao khi sửa lệnh: {', '.join(e.message for e in risk_events)}")

            # Điều chỉnh giá/số lượng mới
            if new_quantity:
                new_quantity = self._adjust_quantity(new_quantity, symbol_info)
            if new_price:
                new_price = self._adjust_price(new_price, symbol_info)
            if new_stop_price:
                new_stop_price = self._adjust_price(new_stop_price, symbol_info)

            response = {}
            if not self.backtest_mode:
                response = await self.exchange.modify_order(symbol, order_id, new_quantity, new_price, new_stop_price)
            else:
                response = order.copy()
                if new_quantity:
                    response["quantity"] = f"{new_quantity:.3f}"
                if new_price:
                    response["price"] = f"{new_price:.2f}"
                if new_stop_price:
                    response["stopPrice"] = f"{new_stop_price:.2f}"

            # Cập nhật self.orders
            status = order.get("status", OrderStatus.NEW.value)
            if symbol in self.orders and status in self.orders[symbol]:
                for i, o in enumerate(self.orders[symbol][status]):
                    if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id:
                        self.orders[symbol][status][i] = response
                        break
            logger.info(
                "Order %s: symbol=%s, order_id=%s",
                "simulated modify" if self.backtest_mode else "modified",
                symbol,
                order_id,
            )

            # Đồng bộ Portfolio và AccountInfo
            self.portfolio._sync_from_account_info()
            return response
        except Exception as e:
            logger.error(
                "Failed to %s order %s for %s: %s",
                "simulate modify" if self.backtest_mode else "modify",
                order_id,
                symbol,
                str(e),
                exc_info=True,
            )
            return {}

    async def modify_multiple_orders(self, symbol: str, modifications: List[Dict[str, Any]]) -> List[Dict]:
        """
        Sửa hoặc mô phỏng sửa nhiều lệnh cùng lúc.

        Args:
            symbol: Cặp giao dịch.
            modifications: Danh sách sửa đổi (order_id, new_quantity, new_price, new_stop_price).

        Returns:
            Danh sách phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            responses = []
            for mod in modifications:
                response = await self.modify_order(
                    symbol=symbol,
                    order_id=mod.get("order_id"),
                    new_quantity=mod.get("new_quantity"),
                    new_price=mod.get("new_price"),
                    new_stop_price=mod.get("new_stop_price"),
                )
                responses.append(response)
            logger.info(
                "%s %d orders for symbol %s",
                "Simulated modification of" if self.backtest_mode else "Modified",
                len(responses),
                symbol,
            )
            return responses
        except Exception as e:
            logger.error(
                "Failed to %s multiple orders for %s: %s",
                "simulate modify" if self.backtest_mode else "modify",
                symbol,
                str(e),
                exc_info=True,
            )
            return []

    async def get_order_modify_history(self, symbol: str, order_id: str) -> List[Dict]:
        """
        Lấy lịch sử sửa đổi của một lệnh.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.

        Returns:
            Danh sách lịch sử sửa đổi.
        """
        try:
            if self.backtest_mode:
                logger.warning("Order modify history not available in backtest mode")
                return []
            response = await self.exchange.get_order_modify_history(symbol, order_id)
            logger.info("Retrieved order modify history: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error(
                "Failed to get order modify history for %s, %s: %s",
                symbol,
                order_id,
                str(e),
                exc_info=True,
            )
            return []

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """
        Hủy hoặc mô phỏng hủy một lệnh.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.

        Returns:
            Phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            # Kiểm tra rủi ro khi hủy lệnh
            if self.risk_manager:
                order = self._find_order(symbol, order_id)
                if order:
                    signal = {"size": float(order.get("quantity", 0)) * float(order.get("price", self._get_current_price(symbol)))}
                    risk_events = self.risk_manager.check_risk(symbol, order.get("side"), signal, is_cancel=True)
                    if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                        raise ValueError(f"Rủi ro cao khi hủy lệnh: {', '.join(e.message for e in risk_events)}")

            response = {}
            if not self.backtest_mode:
                response = await self.exchange.cancel_order(symbol, order_id)
            else:
                order = self._find_order(symbol, order_id)
                if order:
                    response = order.copy()
                    response["status"] = OrderStatus.CANCELED.value

            # Cập nhật self.orders
            if symbol in self.orders:
                for status in self.orders[symbol]:
                    self.orders[symbol][status] = [
                        o for o in self.orders[symbol][status]
                        if o.get("orderId") != order_id and o.get("newClientOrderId") != order_id
                    ]
            logger.info(
                "Order %s: symbol=%s, order_id=%s",
                "simulated cancel" if self.backtest_mode else "canceled",
                symbol,
                order_id,
            )

            # Đồng bộ Portfolio và AccountInfo
            self.portfolio._sync_from_account_info()
            return response
        except Exception as e:
            logger.error(
                "Failed to %s order %s for %s: %s",
                "simulate cancel" if self.backtest_mode else "cancel",
                order_id,
                symbol,
                str(e),
                exc_info=True,
            )
            return {}

    async def cancel_multiple_orders(self, symbol: str, order_ids: List[str]) -> List[Dict]:
        """
        Hủy hoặc mô phỏng hủy nhiều lệnh cùng lúc.

        Args:
            symbol: Cặp giao dịch.
            order_ids: Danh sách ID lệnh.

        Returns:
            Danh sách phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            responses = []
            for order_id in order_ids:
                response = await self.cancel_order(symbol, order_id)
                responses.append(response)
            logger.info(
                "%s %d orders for symbol %s",
                "Simulated cancellation of" if self.backtest_mode else "Canceled",
                len(responses),
                symbol,
            )
            return responses
        except Exception as e:
            logger.error(
                "Failed to %s multiple orders for %s: %s",
                "simulate cancel" if self.backtest_mode else "cancel",
                symbol,
                str(e),
                exc_info=True,
            )
            return []

    async def cancel_all_open_orders(self, symbol: str) -> Dict:
        """
        Hủy hoặc mô phỏng hủy tất cả lệnh đang mở cho một symbol.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Phản hồi từ sàn hoặc mô phỏng.
        """
        try:
            # Kiểm tra rủi ro khi hủy tất cả lệnh
            if self.risk_manager:
                open_orders = await self.query_current_all_open_orders(symbol)
                for order in open_orders:
                    signal = {"size": float(order.get("quantity", 0)) * float(order.get("price", self._get_current_price(symbol)))}
                    risk_events = self.risk_manager.check_risk(symbol, order.get("side"), signal, is_cancel=True)
                    if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                        raise ValueError(f"Rủi ro cao khi hủy tất cả lệnh: {', '.join(e.message for e in risk_events)}")

            response = {}
            if not self.backtest_mode:
                response = await self.exchange.cancel_all_open_orders(symbol)
            else:
                response = {"symbol": symbol, "status": "CANCELED_ALL"}
                if symbol in self.orders:
                    self.orders[symbol]["NEW"] = []
                    self.orders[symbol]["PARTIALLY_FILLED"] = []

            if symbol in self.orders:
                self.orders[symbol]["NEW"] = []
                self.orders[symbol]["PARTIALLY_FILLED"] = []
            logger.info(
                "All open orders %s for symbol %s",
                "simulated canceled" if self.backtest_mode else "canceled",
                symbol,
            )

            # Đồng bộ Portfolio và AccountInfo
            self.portfolio._sync_from_account_info()
            return response
        except Exception as e:
            logger.error(
                "Failed to %s all open orders for %s: %s",
                "simulate cancel" if self.backtest_mode else "cancel",
                symbol,
                str(e),
                exc_info=True,
            )
            return {}

    async def auto_cancel_all_open_orders(self, symbols: List[str], timeout: float = 3600.0) -> None:
        """
        Tự động hủy tất cả lệnh đang mở sau một khoảng thời gian.

        Args:
            symbols: Danh sách cặp giao dịch.
            timeout: Thời gian chờ (giây).
        """
        try:
            await asyncio.sleep(timeout)
            for symbol in symbols:
                await self.cancel_all_open_orders(symbol)
            logger.info(
                "Auto-%s all open orders for symbols: %s",
                "simulated canceled" if self.backtest_mode else "canceled",
                symbols,
            )
        except Exception as e:
            logger.error(
                "Failed to auto-%s open orders: %s",
                "simulate cancel" if self.backtest_mode else "cancel",
                str(e),
                exc_info=True,
            )

    async def query_order(self, symbol: str, order_id: str) -> Dict:
        """
        Truy vấn hoặc mô phỏng truy vấn thông tin một lệnh.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.

        Returns:
            Thông tin lệnh.
        """
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.get_order_status(symbol, order_id)
            else:
                response = self._find_order(symbol, order_id) or {}
            logger.info("Queried order: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error(
                "Failed to query order %s for %s: %s",
                order_id,
                symbol,
                str(e),
                exc_info=True,
            )
            return {}

    async def query_all_orders(self, symbol: str, limit: int = 1000) -> List[Dict]:
        """
        Truy vấn hoặc mô phỏng truy vấn tất cả lệnh cho một symbol.

        Args:
            symbol: Cặp giao dịch.
            limit: Giới hạn số lượng lệnh trả về.

        Returns:
            Danh sách lệnh.
        """
        try:
            response = []
            if not self.backtest_mode:
                response = await self.exchange.query_all_orders(symbol, limit)
            else:
                if symbol in self.orders:
                    response = [
                        o for status in self.orders[symbol] for o in self.orders[symbol][status]
                    ][:limit]
            logger.info("Queried all orders for symbol %s, count=%d", symbol, len(response))
            return response
        except Exception as e:
            logger.error(
                "Failed to query all orders for %s: %s",
                symbol,
                str(e),
                exc_info=True,
            )
            return []

    async def query_current_all_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Truy vấn hoặc mô phỏng truy vấn tất cả lệnh đang mở.

        Args:
            symbol: Cặp giao dịch (tùy chọn).

        Returns:
            Danh sách lệnh đang mở.
        """
        try:
            response = []
            if not self.backtest_mode:
                response = await self.exchange.query_current_all_open_orders(symbol)
            else:
                if symbol and symbol in self.orders:
                    response = (
                        self.orders[symbol]["NEW"] + self.orders[symbol]["PARTIALLY_FILLED"]
                    )
                else:
                    response = [
                        o
                        for s in self.orders
                        for o in (self.orders[s]["NEW"] + self.orders[s]["PARTIALLY_FILLED"])
                    ]
            logger.info(
                "Queried current open orders for symbol %s, count=%d",
                symbol or "all",
                len(response),
            )
            return response
        except Exception as e:
            logger.error(
                "Failed to query current open orders for %s: %s",
                symbol or "all",
                str(e),
                exc_info=True,
            )
            return []

    async def query_current_open_order(self, symbol: str, order_id: str) -> Dict:
        """
        Truy vấn hoặc mô phỏng truy vấn một lệnh đang mở cụ thể.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.

        Returns:
            Thông tin lệnh đang mở.
        """
        try:
            response = {}
            if not self.backtest_mode:
                response = await self.exchange.query_current_open_order(symbol, order_id)
            else:
                order = self._find_order(symbol, order_id)
                if order and order.get("status") in [OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value]:
                    response = order
            logger.info("Queried current open order: symbol=%s, order_id=%s", symbol, order_id)
            return response
        except Exception as e:
            logger.error(
                "Failed to query current open order %s for %s: %s",
                order_id,
                symbol,
                str(e),
                exc_info=True,
            )
            return {}

    async def query_users_force_orders(
        self, symbol: Optional[str] = None, auto_close_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Truy vấn hoặc mô phỏng truy vấn các lệnh bị buộc đóng.

        Args:
            symbol: Cặp giao dịch (tùy chọn).
            auto_close_type: Loại đóng lệnh tự động.

        Returns:
            Danh sách lệnh bị buộc đóng.
        """
        try:
            if self.backtest_mode:
                logger.warning("Force orders not available in backtest mode")
                return []
            response = await self.exchange.query_users_force_orders(symbol, auto_close_type)
            logger.info(
                "Queried force orders for symbol %s, count=%d",
                symbol or "all",
                len(response),
            )
            return response
        except Exception as e:
            logger.error(
                "Failed to query force orders for %s: %s",
                symbol or "all",
                str(e),
                exc_info=True,
            )
            return []

    async def ws_update(self, data: Dict[str, Any]):
        """
        Cập nhật trạng thái lệnh từ dữ liệu WebSocket.

        Args:
            data: Dữ liệu từ Binance Futures WebSocket.
        """
        try:
            symbol = data.get("s")
            order_id = data.get("i") or data.get("c")
            status = data.get("X")
            if not symbol or not order_id or not status:
                logger.warning(f"Dữ liệu WebSocket không hợp lệ: {data}")
                return

            # Kiểm tra và cập nhật lệnh
            if symbol in self.orders:
                for old_status in self.orders[symbol]:
                    for i, o in enumerate(self.orders[symbol][old_status]):
                        if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id:
                            self.orders[symbol][old_status].pop(i)
                            self.orders[symbol][status].append(data)
                            break
            else:
                self.orders[symbol] = {
                    "NEW": [],
                    "FILLED": [],
                    "CANCELED": [],
                    "PARTIALLY_FILLED": [],
                }
                self.orders[symbol][status].append(data)

            # Đồng bộ Portfolio và AccountInfo
            self.portfolio.ws_update(data)
            if self.account:
                await self.account.initial()
                self.portfolio._sync_from_account_info()

            logger.info(f"Updated order via WebSocket: symbol={symbol}, order_id={order_id}, status={status}")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật WebSocket cho {symbol}: {str(e)}")

    async def _order_response_for_test_only(self, order: Order) -> Order:
        """
        Mô phỏng phản hồi lệnh trong chế độ backtest.

        Args:
            order: Lệnh giao dịch.

        Returns:
            Đối tượng Order với trạng thái mô phỏng.
        """
        try:
            order.executed_qty = order.quantity
            order.order_id = str(uuid.uuid4())
            order.avg_price = order.price or self._get_current_price(order.symbol)
            order.status = OrderStatus.FILLED
            order.fee = order.calculate_fee(is_maker=order.type == OrderType.LIMIT,
                                          maker_fee=self._get_symbol_info(order.symbol).maker_commission_rate,
                                          taker_fee=self._get_symbol_info(order.symbol).taker_commission_rate)
            return order
        except Exception as e:
            logger.error(f"Lỗi khi mô phỏng phản hồi lệnh cho {order.symbol}: {str(e)}")
            return order

    def _get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """
        Lấy SymbolInfo cho symbol.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Đối tượng SymbolInfo hoặc None.
        """
        try:
            return self.symbol_info_map.get(symbol)
        except Exception as e:
            logger.error(f"Lỗi khi lấy SymbolInfo cho {symbol}: {str(e)}")
            return None

    def _adjust_quantity(self, quantity: float, symbol_info: SymbolInfo) -> float:
        """
        Điều chỉnh số lượng theo step_size.

        Args:
            quantity: Số lượng cần điều chỉnh.
            symbol_info: Thông tin cặp giao dịch.

        Returns:
            Số lượng đã điều chỉnh.
        """
        try:
            step_size = float(symbol_info.step_size)
            precision = symbol_info.quantity_precision
            return round(round(quantity / step_size) * step_size, precision)
        except Exception as e:
            logger.error(f"Lỗi khi điều chỉnh số lượng: {str(e)}")
            return quantity

    def _adjust_price(self, price: float, symbol_info: SymbolInfo) -> float:
        """
        Điều chỉnh giá theo tick_size.

        Args:
            price: Giá cần điều chỉnh.
            symbol_info: Thông tin cặp giao dịch.

        Returns:
            Giá đã điều chỉnh.
        """
        try:
            tick_size = float(symbol_info.tick_size)
            precision = symbol_info.price_precision
            return round(round(price / tick_size) * tick_size, precision)
        except Exception as e:
            logger.error(f"Lỗi khi điều chỉnh giá: {str(e)}")
            return price

    def _get_current_price(self, symbol: str) -> float:
        """
        Lấy giá thị trường hiện tại (mô phỏng trong backtest).

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Giá thị trường.
        """
        try:
            # Trong môi trường thực, cần gọi API để lấy giá
            return 50000.0  # Giá giả lập cho backtest
        except Exception as e:
            logger.error(f"Lỗi khi lấy giá thị trường cho {symbol}: {str(e)}")
            return 0.0

    def _find_order(self, symbol: str, order_id: str) -> Optional[Dict]:
        """
        Tìm lệnh theo symbol và order_id.

        Args:
            symbol: Cặp giao dịch.
            order_id: ID của lệnh.

        Returns:
            Thông tin lệnh hoặc None.
        """
        try:
            if symbol in self.orders:
                for status in self.orders[symbol]:
                    for o in self.orders[symbol][status]:
                        if o.get("orderId") == order_id or o.get("newClientOrderId") == order_id:
                            return o
            return None
        except Exception as e:
            logger.error(f"Lỗi khi tìm lệnh {order_id} cho {symbol}: {str(e)}")
            return None

    def _check_balance(self, order: Order, symbol_info: SymbolInfo) -> bool:
        """
        Kiểm tra số dư khả dụng để đặt lệnh.

        Args:
            order: Lệnh giao dịch.
            symbol_info: Thông tin cặp giao dịch.

        Returns:
            True nếu số dư đủ, False nếu không.
        """
        try:
            notional = order.quantity * (order.price or self._get_current_price(order.symbol))
            initial_margin = notional / symbol_info.leverage
            fee = order.calculate_fee(
                is_maker=order.type == OrderType.LIMIT,
                maker_fee=symbol_info.maker_commission_rate,
                taker_fee=symbol_info.taker_commission_rate,
            )
            required_balance = initial_margin + fee
            available_balance = self.account.available_balance if self.account else self.portfolio.wallet_balance
            return available_balance >= required_balance
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra số dư cho {order.symbol}: {str(e)}")
            return False