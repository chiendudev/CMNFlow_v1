from typing import Dict, Optional, List
from aiohttp import ClientSession
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential
from src.core.settings import Settings
from src.exchange.rest.base_exchange_client import BaseExchangeClient
import logging

logger = logging.getLogger(__name__)

class TradeClient(BaseExchangeClient):
    """Lớp xử lý các REST API giao dịch trên Binance Futures."""

    def __init__(self, settings: Settings, session: ClientSession):
        super().__init__(settings, session)

    async def new_order(
            self, **kwargs) -> Dict:
        """Tạo lệnh mới."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tạo lệnh {kwargs}")
            return kwargs

        params = {
            **kwargs,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        return await self._make_request("/fapi/v1/order", params, method="POST", signed=True)

    async def place_multiple_orders(self, batch_orders: List[Dict]):
        """Đặt nhiều lệnh cùng lúc."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập đặt nhiều lệnh")
            return [{"orderId": 123456 + i, "symbol": order.get("symbol"), "status": "NEW"} for i, order in
                    enumerate(batch_orders)]

        params = {"batchOrders": batch_orders}
        return await self._make_request("/fapi/v1/batchOrders", params, method="POST", signed=True)

    async def modify_order(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            client_order_id: Optional[str] = None,
            quantity: Optional[float] = None,
            price: Optional[float] = None,
            stop_price: Optional[float] = None
    ) -> Dict:
        """Sửa đổi lệnh hiện có."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập sửa đổi lệnh cho {symbol}")
            return {"orderId": order_id or 123456, "symbol": symbol, "status": "MODIFIED"}

        params = {
            "symbol": symbol,
            "orderId": order_id,
            "origClientOrderId": client_order_id,
            "quantity": quantity,
            "price": price,
            "stopPrice": stop_price
        }
        return await self._make_request("/fapi/v1/order", params, method="PUT", signed=True)

    async def modify_multiple_orders(self, batch_orders: List[Dict]):
        """Sửa đổi nhiều lệnh cùng lúc."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập sửa đổi nhiều lệnh")
            return [{"orderId": order.get("orderId", 123456), "symbol": order.get("symbol"), "status": "MODIFIED"} for
                    order in batch_orders]

        params = {"batchOrders": batch_orders}
        return await self._make_request("/fapi/v1/batchOrders", params, method="PUT", signed=True)

    async def get_order_modify_history(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            client_order_id: Optional[str] = None,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            limit: Optional[int] = 100
    ) -> Dict:
        """Lấy lịch sử sửa đổi lệnh."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập lịch sử sửa đổi lệnh cho {symbol}")
            return {"history": []}

        params = {
            "symbol": symbol,
            "orderId": order_id,
            "origClientOrderId": client_order_id,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit
        }
        return await self._make_request("/fapi/v1/orderModifyHistory", params, method="GET", signed=True)

    async def cancel_order(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            client_order_id: Optional[str] = None
    ) -> Dict:
        """Hủy lệnh."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập hủy lệnh cho {symbol}")
            return {"orderId": order_id or 123456, "symbol": symbol, "status": "CANCELED"}

        params = {"symbol": symbol, "orderId": order_id, "origClientOrderId": client_order_id}
        return await self._make_request("/fapi/v1/order", params, method="DELETE", signed=True)

    async def cancel_multiple_orders(self, symbol: str, order_id_list: Optional[List[int]] = None,
                                     client_order_id_list: Optional[List[str]] = None) -> Dict:
        """Hủy nhiều lệnh cùng lúc."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập hủy nhiều lệnh cho {symbol}")
            return {"canceledOrders": order_id_list or client_order_id_list or []}

        params = {"symbol": symbol, "orderIdList": order_id_list, "origClientOrderIdList": client_order_id_list}
        return await self._make_request("/fapi/v1/batchOrders", params, method="DELETE", signed=True)

    async def cancel_all_open_orders(self, symbol: str) -> Dict:
        """Hủy tất cả lệnh đang mở."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập hủy tất cả lệnh mở cho {symbol}")
            return {"code": 200, "msg": "Success"}

        params = {"symbol": symbol}
        return await self._make_request("/fapi/v1/allOpenOrders", params, method="DELETE", signed=True)

    async def auto_cancel_all_open_orders(self, symbol: str, countdown_time: int) -> Dict:
        """Tự động hủy tất cả lệnh mở sau thời gian đếm ngược."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tự động hủy lệnh cho {symbol}")
            return {"code": 200, "msg": "Success"}

        params = {"symbol": symbol, "countdownTime": countdown_time}
        return await self._make_request("/fapi/v1/countdownCancelAll", params, method="POST", signed=True)

    async def query_order(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            client_order_id: Optional[str] = None
    ) -> Dict:
        """Tra cứu thông tin lệnh."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tra cứu lệnh cho {symbol}")
            return {"orderId": order_id or 123456, "symbol": symbol, "status": "FILLED"}

        params = {"symbol": symbol, "orderId": order_id, "origClientOrderId": client_order_id}
        return await self._make_request("/fapi/v1/order", params, method="GET", signed=True)

    async def query_all_orders(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            limit: Optional[int] = 500
    ):
        """Tra cứu tất cả lệnh."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tra cứu tất cả lệnh cho {symbol}")
            return [{"orderId": 123456, "symbol": symbol, "status": "FILLED"}]

        params = {"symbol": symbol, "orderId": order_id, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/allOrders", params, method="GET", signed=True)

    async def query_current_all_open_orders(self, symbol: Optional[str] = None):
        """Tra cứu tất cả lệnh đang mở."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tra cứu lệnh đang mở cho {symbol or 'all'}")
            return []

        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/openOrders", params, method="GET", signed=True)

    async def query_current_open_order(
            self,
            symbol: str,
            order_id: Optional[int] = None,
            client_order_id: Optional[str] = None
    ) -> Dict:
        """Tra cứu lệnh đang mở cụ thể."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tra cứu lệnh đang mở cho {symbol}")
            return {"orderId": order_id or 123456, "symbol": symbol, "status": "NEW"}

        params = {"symbol": symbol, "orderId": order_id, "origClientOrderId": client_order_id}
        return await self._make_request("/fapi/v1/openOrder", params, method="GET", signed=True)

    async def query_users_force_orders(self, symbol: Optional[str] = None, auto_close_type: Optional[str] = None,
                                       start_time: Optional[int] = None, end_time: Optional[int] = None,
                                       limit: Optional[int] = 50):
        """Tra cứu lệnh bị buộc đóng (liquidation)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tra cứu lệnh buộc đóng cho {symbol or 'all'}")
            return []

        params = {"symbol": symbol, "autoCloseType": auto_close_type, "startTime": start_time, "endTime": end_time,
                  "limit": limit}
        return await self._make_request("/fapi/v1/forceOrders", params, method="GET", signed=True)

    async def query_account_trade_list(
            self,
            symbol: str,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            from_id: Optional[int] = None,
            limit: Optional[int] = 500
    ):
        """Lấy danh sách giao dịch của tài khoản."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập danh sách giao dịch cho {symbol}")
            return [{"tradeId": 789, "symbol": symbol, "side": "BUY"}]

        params = {"symbol": symbol, "startTime": start_time, "endTime": end_time, "fromId": from_id, "limit": limit}
        return await self._make_request("/fapi/v1/userTrades", params, method="GET", signed=True)

    async def change_margin_type(self, symbol: str, margin_type: str) -> Dict:
        """Thay đổi loại margin (ISOLATED hoặc CROSSED)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thay đổi margin type cho {symbol}")
            return {"code": 200, "msg": "Success"}

        params = {"symbol": symbol, "marginType": margin_type}
        return await self._make_request("/fapi/v1/marginType", params, method="POST", signed=True)

    async def change_position_mode(self, dual_side_position: bool) -> Dict:
        """Thay đổi chế độ vị thế (Hedging hoặc One-way)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thay đổi chế độ vị thế")
            return {"code": 200, "msg": "Success"}

        params = {"dualSidePosition": "true" if dual_side_position else "false"}
        return await self._make_request("/fapi/v1/positionSide/dual", params, method="POST", signed=True)

    async def change_initial_leverage(self, symbol: str, leverage: int) -> Dict:
        """Thay đổi đòn bẩy ban đầu."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thay đổi đòn bẩy cho {symbol}")
            return {"symbol": symbol, "leverage": leverage}

        params = {"symbol": symbol, "leverage": leverage}
        return await self._make_request("/fapi/v1/leverage", params, method="POST", signed=True)

    async def change_multi_assets_mode(self, multi_assets_margin: bool) -> Dict:
        """Thay đổi chế độ đa tài sản."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thay đổi chế độ đa tài sản")
            return {"code": 200, "msg": "Success"}

        params = {"multiAssetsMargin": "true" if multi_assets_margin else "false"}
        return await self._make_request("/fapi/v1/multiAssetsMargin", params, method="POST", signed=True)

    async def modify_isolated_position_margin(
            self,
            symbol: str,
            amount: float,
            is_add: bool = True,
            position_side: Optional[str] = None
    ) -> Dict:
        """Sửa đổi margin vị thế isolated."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập sửa đổi margin vị thế cho {symbol}")
            return {"symbol": symbol, "amount": amount}

        params = {"symbol": symbol, "amount": amount, "type": 1 if is_add else 2, "positionSide": position_side}
        return await self._make_request("/fapi/v1/positionMargin", params, method="POST", signed=True)

    async def get_position_information_v2(self, symbol: Optional[str] = None):
        """Lấy thông tin vị thế (V2)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thông tin vị thế cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "positionAmt": 0.1, "entryPrice": 50000.0}]

        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v2/positionRisk", params, method="GET", signed=True)

    async def get_position_information_v3(self, symbol: Optional[str] = None, margin_asset: Optional[str] = None,
                                          pair: Optional[str] = None):
        """Lấy thông tin vị thế (V3)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập thông tin vị thế V3 cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "positionAmt": 0.1, "entryPrice": 50000.0}]

        params = {"symbol": symbol, "marginAsset": margin_asset, "pair": pair}
        return await self._make_request("/fapi/v3/positionRisk", params, method="GET", signed=True)

    async def get_position_adl_quantile(self, symbol: Optional[str] = None):
        """Lấy ước lượng phân vị ADL vị thế."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập ước lượng ADL cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "adlQuantile": 0}]

        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/adlQuantile", params, method="GET", signed=True)

    async def get_position_margin_change_history(
            self,
            symbol: str,
            type: Optional[int] = None,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            limit: Optional[int] = 100
    ):
        """Lấy lịch sử thay đổi margin vị thế."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập lịch sử thay đổi margin cho {symbol}")
            return []

        params = {"symbol": symbol, "type": type, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/positionMargin/history", params, method="GET", signed=True)

    async def test_new_order(self, **kwargs) -> Dict:
        """Kiểm tra lệnh mới (không thực thi)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập kiểm tra lệnh {kwargs}")
            return {"code": 200, "msg": "Test Success"}

        params = {
            **kwargs,
            'timestamp': int(datetime.now().timestamp() * 1000)
        }
        return await self._make_request("/fapi/v1/order/test", params, method="POST", signed=True)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_exchange_info(self) -> Dict:
        return await self._make_request("/fapi/v1/exchangeInfo")