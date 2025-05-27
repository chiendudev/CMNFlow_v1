from typing import Dict, Optional, List
from aiohttp import ClientSession
from src.core.settings import Settings
from src.exchange.rest.base_exchange_client import BaseExchangeClient
import logging

logger = logging.getLogger(__name__)

class MarketDataClient(BaseExchangeClient):
    """Lớp lấy dữ liệu thị trường từ Binance Futures."""
    def __init__(self, settings: Settings, session: ClientSession):
        super().__init__(settings, session) # URL API Futures

    async def test_connectivity(self) -> Dict:
        """Kiểm tra kết nối tới server."""
        return await self._make_request("/fapi/v1/ping")

    async def check_server_time(self) -> Dict:
        """Lấy thời gian server."""
        return await self._make_request("/fapi/v1/time")

    async def get_exchange_info(self) -> Dict:
        """Lấy thông tin sàn giao dịch."""
        return await self._make_request("/fapi/v1/exchangeInfo")

    async def get_order_book(self, symbol: str, limit: Optional[int] = 100) -> Dict:
        """Lấy sổ lệnh cho một symbol."""
        params = {"symbol": symbol, "limit": limit}
        return await self._make_request("/fapi/v1/depth", params)

    async def get_recent_trades(self, symbol: str, limit: Optional[int] = 500) -> List[Dict]:
        """Lấy danh sách giao dịch gần đây."""
        params = {"symbol": symbol, "limit": limit}
        return await self._make_request("/fapi/v1/trades", params)

    async def get_old_trades(self, symbol: str, limit: Optional[int] = 500, from_id: Optional[int] = None) -> List[Dict]:
        """Tra cứu lịch sử giao dịch cũ."""
        params = {"symbol": symbol, "limit": limit, "fromId": from_id}
        return await self._make_request("/fapi/v1/historicalTrades", params)

    async def get_aggregate_trades(self, symbol: str, from_id: Optional[int] = None, start_time: Optional[int] = None,
                                   end_time: Optional[int] = None, limit: Optional[int] = 500) -> List[Dict]:
        """Lấy danh sách giao dịch tổng hợp."""
        params = {"symbol": symbol, "fromId": from_id, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/aggTrades", params)

    async def get_kline_data(self, symbol: str, interval: str, start_time: Optional[int] = None,
                             end_time: Optional[int] = None, limit: Optional[int] = 500) -> List[List]:
        """Lấy dữ liệu nến (Kline/Candlestick)."""
        params = {"symbol": symbol, "interval": interval, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/klines", params)

    async def get_continuous_kline_data(self, pair: str, contract_type: str, interval: str,
                                        start_time: Optional[int] = None, end_time: Optional[int] = None,
                                        limit: Optional[int] = 500) -> List[List]:
        """Lấy dữ liệu nến hợp đồng liên tục."""
        params = {"pair": pair, "contractType": contract_type, "interval": interval,
                  "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/continuousKlines", params)

    async def get_index_price_kline_data(self, pair: str, interval: str, start_time: Optional[int] = None,
                                         end_time: Optional[int] = None, limit: Optional[int] = 500) -> List[List]:
        """Lấy dữ liệu nến giá chỉ số."""
        params = {"pair": pair, "interval": interval, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/indexPriceKlines", params)

    async def get_mark_price_kline_data(self, symbol: str, interval: str, start_time: Optional[int] = None,
                                        end_time: Optional[int] = None, limit: Optional[int] = 500) -> List[List]:
        """Lấy dữ liệu nến giá đánh dấu (mark price)."""
        params = {"symbol": symbol, "interval": interval, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/markPriceKlines", params)

    async def get_premium_index_kline_data(self, symbol: str, interval: str, start_time: Optional[int] = None,
                                           end_time: Optional[int] = None, limit: Optional[int] = 500) -> List[List]:
        """Lấy dữ liệu nến chỉ số premium."""
        params = {"symbol": symbol, "interval": interval, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/premiumIndexKlines", params)

    async def get_mark_price(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy giá đánh dấu (mark price)."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/premiumIndex", params)

    async def get_funding_rate_history(self, symbol: str, start_time: Optional[int] = None,
                                       end_time: Optional[int] = None, limit: Optional[int] = 100) -> List[Dict]:
        """Lấy lịch sử tỷ lệ funding."""
        params = {"symbol": symbol, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/fapi/v1/fundingRate", params)

    async def get_funding_info(self) -> List[Dict]:
        """Lấy thông tin funding."""
        return await self._make_request("/fapi/v1/fundingInfo")

    async def get_24hr_ticker(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy thống kê giá thay đổi trong 24 giờ."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/ticker/24hr", params)

    async def get_symbol_price_ticker(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy giá hiện tại của symbol."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/ticker/price", params)

    async def get_symbol_price_ticker_v2(self, symbol: Optional[str] = None, pair: Optional[str] = None) -> List[Dict]:
        """Lấy giá hiện tại của symbol hoặc pair (V2)."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        if pair:
            params["pair"] = pair
        return await self._make_request("/fapi/v2/ticker/price", params)

    async def get_order_book_ticker(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy giá bid/ask tốt nhất từ sổ lệnh."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/ticker/bookTicker", params)

    async def get_delivery_price(self, pair: str, delivery_date: Optional[int] = None) -> Dict:
        """Lấy giá giao hàng."""
        params = {"pair": pair, "deliveryDate": delivery_date}
        return await self._make_request("/fapi/v1/delivery/price", params)

    async def get_open_interest(self, symbol: str) -> Dict:
        """Lấy lãi suất mở (open interest)."""
        params = {"symbol": symbol}
        return await self._make_request("/fapi/v1/openInterest", params)

    async def get_open_interest_stats(self, symbol: str, period: str, start_time: Optional[int] = None,
                                      end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy thống kê lãi suất mở."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/openInterestHist", params)

    async def get_top_trader_long_short_position_ratio(self, symbol: str, period: str, start_time: Optional[int] = None,
                                                       end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy tỷ lệ vị thế long/short của các trader hàng đầu."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/topLongShortPositionRatio", params)

    async def get_top_trader_long_short_account_ratio(self, symbol: str, period: str, start_time: Optional[int] = None,
                                                      end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy tỷ lệ tài khoản long/short của các trader hàng đầu."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/topLongShortAccountRatio", params)

    async def get_long_short_ratio(self, symbol: str, period: str, start_time: Optional[int] = None,
                                   end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy tỷ lệ long/short tổng thể."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/globalLongShortAccountRatio", params)

    async def get_taker_buy_sell_volume(self, symbol: str, period: str, start_time: Optional[int] = None,
                                        end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy khối lượng mua/bán của taker."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/takerlongshortRatio", params)

    async def get_basis(self, symbol: str, period: str, start_time: Optional[int] = None,
                        end_time: Optional[int] = None, limit: Optional[int] = 30) -> List[Dict]:
        """Lấy dữ liệu basis."""
        params = {"symbol": symbol, "period": period, "startTime": start_time, "endTime": end_time, "limit": limit}
        return await self._make_request("/futures/data/basis", params)

    async def get_composite_index_info(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy thông tin chỉ số tổng hợp."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/constituents", params)

    async def get_multi_assets_mode_index(self, symbol: Optional[str] = None) -> List[Dict]:
        """Lấy chỉ số tài sản chế độ đa tài sản."""
        params = {"symbol": symbol} if symbol else {}
        return await self._make_request("/fapi/v1/assetIndex", params)

    async def get_index_price_constituents(self, symbol: str) -> Dict:
        """Lấy thành phần giá chỉ số."""
        params = {"symbol": symbol}
        return await self._make_request("/fapi/v1/indexInfo", params)

    async def get_insurance_fund_snapshot(self, symbol: str, limit: Optional[int] = 30,
                                          start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[Dict]:
        """Lấy snapshot quỹ bảo hiểm."""
        params = {"symbol": symbol, "limit": limit, "startTime": start_time, "endTime": end_time}
        return await self._make_request("/fapi/v1/insurance", params)