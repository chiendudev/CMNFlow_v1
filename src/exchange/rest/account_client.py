from typing import Dict, Optional
from aiohttp import ClientSession
from src.core.settings import Settings
from src.exchange.rest.base_exchange_client import BaseExchangeClient
import logging
import time

logger = logging.getLogger(__name__)

VALID_TRANSFER_TYPES = {
    "MAIN_UMFUTURE", "UMFUTURE_MAIN", "MAIN_CMFUTURE", "CMFUTURE_MAIN",
    "MAIN_MARGIN", "MARGIN_MAIN", "UMFUTURE_MARGIN", "MARGIN_UMFUTURE",
    "CMFUTURE_MARGIN", "MARGIN_CMFUTURE", "MAIN_FUNDING", "FUNDING_MAIN",
    "FUNDING_UMFUTURE", "UMFUTURE_FUNDING", "MARGIN_FUNDING", "FUNDING_MARGIN",
    "FUNDING_CMFUTURE", "CMFUTURE_FUNDING", "MAIN_OPTION", "OPTION_MAIN",
    "UMFUTURE_OPTION", "OPTION_UMFUTURE", "MARGIN_OPTION", "OPTION_MARGIN",
    "FUNDING_OPTION", "OPTION_FUNDING", "MAIN_PORTFOLIO_MARGIN", "PORTFOLIO_MARGIN_MAIN",
    "ISOLATEDMARGIN_MARGIN", "MARGIN_ISOLATEDMARGIN", "ISOLATEDMARGIN_ISOLATEDMARGIN"
}

REQUIRE_FROM_SYMBOL = {"ISOLATEDMARGIN_MARGIN", "ISOLATEDMARGIN_ISOLATEDMARGIN"}
REQUIRE_TO_SYMBOL = {"MARGIN_ISOLATEDMARGIN", "ISOLATEDMARGIN_ISOLATEDMARGIN"}


class AccountClient(BaseExchangeClient):
    """Lớp xử lý các REST API tài khoản trên Binance Futures."""

    def __init__(self, settings: Settings, session: ClientSession):
        super().__init__(settings, session)

    async def new_future_account_transfer(
            self,
            asset: str,
            amount: float,
            transfer_type: str,
            recv_window: Optional[int] = 5000,
            from_symbol: Optional[str] = None,
            to_symbol: Optional[str] = None
    ) -> Dict:
        """Chuyển tiền giữa các tài khoản Spot/Futures/Margin theo chuẩn Binance."""

        if self.settings.backtest_mode:
            logger.info(f"[Backtest] Giả lập chuyển {amount} {asset} | type={transfer_type}")
            return {"tranId": 123456}

        # Kiểm tra hợp lệ
        if transfer_type not in VALID_TRANSFER_TYPES:
            raise ValueError(
                f"❌ Invalid transfer type: {transfer_type}. Must be one of: {', '.join(VALID_TRANSFER_TYPES)}"
            )
        if amount <= 0:
            raise ValueError("❌ Amount must be greater than 0.")
        if not asset:
            raise ValueError("❌ Asset must be provided.")

        if transfer_type in REQUIRE_FROM_SYMBOL and not from_symbol:
            raise ValueError(f"❌ 'fromSymbol' is required for transfer type '{transfer_type}'.")
        if transfer_type in REQUIRE_TO_SYMBOL and not to_symbol:
            raise ValueError(f"❌ 'toSymbol' is required for transfer type '{transfer_type}'.")

        # Xây params
        params = {
            "asset": asset,
            "amount": f"{amount:.8f}",
            "type": transfer_type,
            "recvWindow": recv_window,
            "timestamp": int(time.time() * 1000),
            "fromSymbol": from_symbol,
            "toSymbol": to_symbol,
        }

        # Clean None
        params = {k: v for k, v in params.items() if v is not None}

        logger.info(f"🔁 Transfer: {amount} {asset} | type: {transfer_type} | from: {from_symbol} → {to_symbol}")
        return await self._make_request(
            "/sapi/v1/asset/transfer",
            params=params,
            method="POST",
            signed=True
        )
    async def get_futures_account_balance_v3(self, recv_window: Optional[int] = 5000):
        """Lấy số dư tài khoản Futures (V3)."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập số dư tài khoản Futures V3")
            return [{"asset": "USDT", "balance": 1000.0, "availableBalance": 800.0}]

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v3/balance", params, method="GET", signed=True)

    async def get_futures_account_balance(self, recv_window: Optional[int] = None):
        """Lấy số dư tài khoản Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập số dư tài khoản Futures")
            return [{"asset": "USDT", "balance": 1000.0, "availableBalance": 800.0}]

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v2/balance", params, method="GET", signed=True)

    async def get_account_information_v3(self, recv_window: Optional[int] = None) -> Dict:
        """Lấy thông tin tài khoản Futures (V3)."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập thông tin tài khoản Futures V3")
            return {
                "feeTier": 0,
                "totalInitialMargin": 100.0,
                "totalWalletBalance": 1000.0,
                "assets": [{"asset": "USDT", "walletBalance": 1000.0}],
                "positions": [{"symbol": "BTCUSDT", "positionAmt": 0.1}]
            }

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v3/account", params, method="GET", signed=True)

    async def get_account_information(self, recv_window: Optional[int] = None) -> Dict:
        """Lấy thông tin tài khoản Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập thông tin tài khoản Futures")
            return {
                "feeTier": 0,
                "totalInitialMargin": 100.0,
                "totalWalletBalance": 1000.0,
                "assets": [{"asset": "USDT", "walletBalance": 1000.0}],
                "positions": [{"symbol": "BTCUSDT", "positionAmt": 0.1}]
            }

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v2/account", params, method="GET", signed=True)

    async def get_future_account_transaction_history(
            self,
            asset: str,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            current: Optional[int] = None,
            size: Optional[int] = None,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy lịch sử giao dịch tài khoản Futures."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập lịch sử giao dịch cho {asset}")
            return {"rows": [], "total": 0}

        params = {
            "asset": asset,
            "startTime": start_time,
            "endTime": end_time,
            "current": current,
            "size": size,
            "recvWindow": recv_window
        }
        return await self._make_request("/sapi/v1/futures/transfer", params, method="GET", signed=True)

    async def get_user_commission_rate(self, symbol: str, recv_window: Optional[int] = None) -> Dict:
        """Lấy tỷ lệ hoa hồng của người dùng."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập tỷ lệ hoa hồng cho {symbol}")
            return {"symbol": symbol, "makerCommissionRate": 0.001, "takerCommissionRate": 0.002}

        params = {"symbol": symbol, "recvWindow": recv_window}
        return await self._make_request("/fapi/v1/commissionRate", params, method="GET", signed=True)

    async def query_account_configuration(self, recv_window: Optional[int] = None) -> Dict:
        """Tra cứu cấu hình tài khoản."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập cấu hình tài khoản")
            return {"dualSidePosition": True}

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v1/positionSide/dual", params, method="GET", signed=True)

    async def query_symbol_configuration(self, symbol: str, recv_window: Optional[int] = None) -> Dict:
        """Tra cứu cấu hình của symbol."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập cấu hình symbol {symbol}")
            return {"symbol": symbol, "leverage": 20}

        params = {"symbol": symbol, "recvWindow": recv_window}
        return await self._make_request("/fapi/v1/leverageBracket", params, method="GET", signed=True)

    async def query_order_rate_limit(self, symbol: Optional[str] = None, recv_window: Optional[int] = None):
        """Tra cứu giới hạn tốc độ đặt lệnh."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập giới hạn tốc độ đặt lệnh cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "rateLimitType": "ORDERS", "interval": "MINUTE", "limit": 1200}]

        params = {"symbol": symbol, "recvWindow": recv_window}
        return await self._make_request("/fapi/v1/rateLimit/order", params, method="GET", signed=True)

    async def get_notional_and_leverage_brackets(self, symbol: Optional[str] = None,
                                                 recv_window: Optional[int] = None):
        """Lấy thông tin khung đòn bẩy và giá trị danh nghĩa."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập khung đòn bẩy cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "brackets": [{"leverage": 20, "maxNotionalValue": 5000000}]}]

        params = {"symbol": symbol, "recvWindow": recv_window}
        return await self._make_request("/fapi/v2/leverageBracket", params, method="GET", signed=True)

    async def get_current_multi_assets_mode(self, recv_window: Optional[int] = None) -> Dict:
        """Lấy chế độ đa tài sản hiện tại."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập chế độ đa tài sản")
            return {"multiAssetsMargin": False}

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v1/multiAssetsMargin", params, method="GET", signed=True)

    async def get_current_position_mode(self, recv_window: Optional[int] = None) -> Dict:
        """Lấy chế độ vị thế hiện tại (Hedging hoặc One-way)."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập chế độ vị thế")
            return {"dualSidePosition": True}

        params = {"recvWindow": recv_window}
        return await self._make_request("/fapi/v1/positionSide/dual", params, method="GET", signed=True)

    async def get_income_history(
            self,
            symbol: Optional[str] = None,
            income_type: Optional[str] = None,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            limit: Optional[int] = 100,
            recv_window: Optional[int] = None):
        """Lấy lịch sử thu nhập (funding, commission, v.v.)."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập lịch sử thu nhập cho {symbol or 'all'}")
            return [{"symbol": symbol or "BTCUSDT", "incomeType": "FUNDING_FEE", "income": -0.01}]

        params = {
            "symbol": symbol,
            "incomeType": income_type,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit,
            "recvWindow": recv_window
        }
        return await self._make_request("/fapi/v1/income", params, method="GET", signed=True)

    async def get_futures_trading_quantitative_rules_indicators(self, symbol: Optional[str] = None,
                                                                recv_window: Optional[int] = None) -> Dict:
        """Lấy các chỉ số quy tắc giao dịch định lượng."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập chỉ số quy tắc định lượng cho {symbol or 'all'}")
            return {"symbol": symbol or "BTCUSDT", "indicators": {"leverage": 20}}

        params = {"symbol": symbol, "recvWindow": recv_window}
        return await self._make_request("/fapi/v1/apiTradingStatus", params, method="GET", signed=True)

    async def get_download_id_for_futures_transaction_history(
            self,
            start_time: int,
            end_time: int,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy ID tải xuống lịch sử giao dịch Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập ID tải xuống lịch sử giao dịch")
            return {"downloadId": "123456"}

        params = {"startTime": start_time, "endTime": end_time, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/histDataId", params, method="POST", signed=True)

    async def get_futures_transaction_history_download_link_by_id(
            self,
            download_id: str,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy link tải xuống lịch sử giao dịch Futures theo ID."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập link tải xuống lịch sử giao dịch {download_id}")
            return {"link": f"https://example.com/download/{download_id}"}

        params = {"downloadId": download_id, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/histDataLink", params, method="GET", signed=True)

    async def get_download_id_for_futures_order_history(
            self,
            start_time: int,
            end_time: int,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy ID tải xuống lịch sử lệnh Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập ID tải xuống lịch sử lệnh")
            return {"downloadId": "123456"}

        params = {"startTime": start_time, "endTime": end_time, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/orderHistoryId", params, method="POST", signed=True)

    async def get_futures_order_history_download_link_by_id(
            self,
            download_id: str,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy link tải xuống lịch sử lệnh Futures theo ID."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập link tải xuống lịch sử lệnh {download_id}")
            return {"link": f"https://example.com/download/{download_id}"}

        params = {"downloadId": download_id, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/orderHistoryLink", params, method="GET", signed=True)

    async def get_download_id_for_futures_trade_history(
            self,
            start_time: int,
            end_time: int,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy ID tải xuống lịch sử giao dịch Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập ID tải xuống lịch sử giao dịch")
            return {"downloadId": "123456"}

        params = {"startTime": start_time, "endTime": end_time, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/tradeHistoryId", params, method="POST", signed=True)

    async def get_futures_trade_download_link_by_id(
            self,
            download_id: str,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Lấy link tải xuống lịch sử giao dịch Futures theo ID."""
        if self.settings.backtest_mode:
            logger.info(f"Backtest mode: Giả lập link tải xuống lịch sử giao dịch {download_id}")
            return {"link": f"https://example.com/download/{download_id}"}

        params = {"downloadId": download_id, "recvWindow": recv_window}
        return await self._make_request("/sapi/v1/futures/tradeHistoryLink", params, method="GET", signed=True)

    async def toggle_bnb_burn_on_futures_trade(
            self,
            spot_bnb_burn: Optional[bool] = None,
            interest_bnb_burn: Optional[bool] = None,
            recv_window: Optional[int] = None
    ) -> Dict:
        """Bật/tắt sử dụng BNB để thanh toán phí giao dịch Futures."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập bật/tắt BNB burn")
            return {"spotBNBBurn": spot_bnb_burn or False, "interestBNBBurn": interest_bnb_burn or False}

        params = {
            "spotBNBBurn": spot_bnb_burn,
            "interestBNBBurn": interest_bnb_burn,
            "recvWindow": recv_window
        }
        return await self._make_request("/sapi/v1/bnbBurn", params, method="POST", signed=True)

    async def get_bnb_burn_status(self, recv_window: Optional[int] = None) -> Dict:
        """Lấy trạng thái sử dụng BNB để thanh toán phí."""
        if self.settings.backtest_mode:
            logger.info("Backtest mode: Giả lập trạng thái BNB burn")
            return {"spotBNBBurn": False, "interestBNBBurn": False}

        params = {"recvWindow": recv_window}
        return await self._make_request("/sapi/v1/bnbBurn", params, method="GET", signed=True)