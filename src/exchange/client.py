from abc import ABC, abstractmethod
from aiohttp import ClientSession
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from src.core.settings import Settings
from src.core.events import OrderBookSnapshot
from src.data.kline import Kline
from src.data.trade import Trade, TradeSummary
from src.trading.enums import KlineIntervals, OrderSide, OrderType, PositionSide
from src.trading.orders import OCOOrder
import hmac
import hashlib
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

class IExchange(ABC):
    @abstractmethod
    async def fetch_klines(self, symbol: str, interval: KlineIntervals, start_time: str, end_time: str) -> List[Kline]:
        pass

    @abstractmethod
    async def fetch_agg_trades(self, symbol: str, start_time: int, end_time: int) -> List[TradeSummary]:
        pass

    @abstractmethod
    async def fetch_trades(self, symbol: str, start_time: int, end_time: int) -> List[Trade]:
        pass

    @abstractmethod
    async def fetch_order_book(self, symbol: str, limit: int = 100) -> OrderBookSnapshot:
        pass

    @abstractmethod
    async def fetch_funding_rate(self, symbol: str, start_time: str, end_time: str) -> List[Dict]:
        pass

    @abstractmethod
    async def fetch_open_interest(self, symbol: str) -> float:
        pass

    @abstractmethod
    async def fetch_mark_price(self, symbol: str) -> float:
        pass

    @abstractmethod
    async def place_order(self, **kwargs) -> Dict:
        pass

    @abstractmethod
    async def place_oco_order(self, oco_order: OCOOrder) -> Dict:
        pass

    @abstractmethod
    async def place_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        pass

    @abstractmethod
    async def modify_order(self, symbol: str, order_id: str, new_quantity: Optional[float] = None, new_price: Optional[float] = None, new_stop_price: Optional[float] = None) -> Dict:
        pass

    @abstractmethod
    async def modify_multiple_orders(self, symbol: str, modifications: List[Dict[str, Any]]) -> List[Dict]:
        pass

    @abstractmethod
    async def get_order_modify_history(self, symbol: str, order_id: str) -> List[Dict]:
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        pass

    @abstractmethod
    async def cancel_multiple_orders(self, symbol: str, order_ids: List[str]) -> List[Dict]:
        pass

    @abstractmethod
    async def cancel_all_open_orders(self, symbol: str) -> Dict:
        pass

    @abstractmethod
    async def query_all_orders(self, symbol: str, limit: int = 1000) -> List[Dict]:
        pass

    @abstractmethod
    async def query_current_all_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    async def query_current_open_order(self, symbol: str, order_id: str) -> Dict:
        pass

    @abstractmethod
    async def query_users_force_orders(self, symbol: Optional[str] = None, auto_close_type: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    async def get_balance(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        pass

    @abstractmethod
    async def set_position_mode(self, dual_side: bool) -> None:
        pass

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: float) -> None:
        pass

    @abstractmethod
    async def get_maintenance_margin_rate(self, symbol: str) -> float:
        pass

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        pass

    @abstractmethod
    async def get_exchange_info(self) -> Dict:
        pass

class ExchangeClient(IExchange):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://testnet.binancefuture.com"
        self.api_key = settings.api_key
        self.api_secret = settings.api_secret
        self.rate_limit = 2400
        self.weight_used = 0

    async def _make_request(self, endpoint: str, params: Dict = None, method: str = "GET") -> Dict:
        headers = {"X-MBX-APIKEY": self.api_key}
        print(f'API key: {self.api_key}')
        params = params or {}

        if method in ["POST", "PUT", "DELETE"]:
            params["timestamp"] = int(datetime.now().timestamp() * 1000)
            query_string = urlencode({k: v for k, v in params.items() if v is not None})
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            params["signature"] = signature

        url = f"{self.base_url}{endpoint}"
        async with ClientSession() as session:
            try:
                if method == "GET":
                    async with session.get(url, params=params, headers=headers) as resp:
                        return await self._handle_response(resp, endpoint)
                elif method == "POST":
                    async with session.post(url, data=params, headers=headers) as resp:
                        return await self._handle_response(resp, endpoint)
                elif method == "PUT":
                    async with session.put(url, data=params, headers=headers) as resp:
                        return await self._handle_response(resp, endpoint)
                elif method == "DELETE":
                    async with session.delete(url, params=params, headers=headers) as resp:
                        return await self._handle_response(resp, endpoint)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
            except Exception as e:
                logger.error("Request error: %s", str(e))
                raise

    async def _handle_response(self, resp, endpoint: str) -> Dict:
        if resp.status != 200:
            logger.error("API request failed: %s, %s", endpoint, await resp.text())
            raise Exception(f"API error: {resp.status}")
        self.weight_used += int(resp.headers.get("x-mbx-used-weight-1m", 0))
        return await resp.json()

    # Các phương thức hiện có (giữ nguyên từ mã bạn cung cấp)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_klines(self, symbol: str, interval: KlineIntervals, start_time: str, end_time: str) -> List[Kline]:
        params = {
            "symbol": symbol,
            "interval": interval.value,
            "startTime": int(datetime.strptime(start_time, "%d/%m/%Y").timestamp() * 1000),
            "endTime": int(datetime.strptime(end_time, "%d/%m/%Y").timestamp() * 1000),
            "limit": 1000
        }
        data = await self._make_request("/fapi/v1/klines", params)
        return [Kline(
            symbol=symbol,
            timeframe=interval.value,
            open_time=int(item[0]),
            close_time=int(item[6]),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            num_trades=int(item[8])
        ) for item in data]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_agg_trades(self, symbol: str, start_time: int, end_time: int) -> List[TradeSummary]:
        params = {"symbol": symbol, "fromId": 0, "limit": 1000}
        data = await self._make_request("/fapi/v1/aggTrades", params)
        trades = [Trade.model_validate(item) for item in data]
        summaries: Dict[float, TradeSummary] = {}
        for trade in trades:
            if start_time <= trade.timestamp <= end_time:
                if trade.price not in summaries:
                    summaries[trade.price] = TradeSummary(price=trade.price, last_update=trade.timestamp)
                summaries[trade.price].update(trade)
        return list(summaries.values())

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_trades(self, symbol: str, start_time: int, end_time: int) -> List[Trade]:
        params = {"symbol": symbol, "limit": 1000}
        data = await self._make_request("/fapi/v1/trades", params)
        return [Trade.model_validate(item) for item in data if start_time <= item["time"] <= end_time]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_order_book(self, symbol: str, limit: int = 100) -> OrderBookSnapshot:
        params = {"symbol": symbol, "limit": limit}
        data = await self._make_request("/fapi/v1/depth", params)
        return OrderBookSnapshot(
            bids=[(float(b[0]), float(b[1])) for b in data["bids"]],
            asks=[(float(a[0]), float(a[1])) for a in data["asks"]],
            timestamp=data["lastUpdateId"]
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_funding_rate(self, symbol: str, start_time: str, end_time: str) -> List[Dict]:
        params = {
            "symbol": symbol,
            "startTime": int(datetime.strptime(start_time, "%d/%m/%Y").timestamp() * 1000),
            "endTime": int(datetime.strptime(end_time, "%d/%m/%Y").timestamp() * 1000),
            "limit": 1000
        }
        data = await self._make_request("/fapi/v1/fundingRate", params)
        return [{"rate": float(item["fundingRate"]), "time": int(item["fundingTime"])} for item in data]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_open_interest(self, symbol: str) -> float:
        params = {"symbol": symbol}
        data = await self._make_request("/fapi/v1/openInterest", params)
        return float(data["openInterest"])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_mark_price(self, symbol: str) -> float:
        params = {"symbol": symbol}
        data = await self._make_request("/fapi/v1/premiumIndex", params)
        return float(data["markPrice"])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def place_order(self, **kwargs) -> Dict:
        params = {
            **kwargs,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/order", params, method="POST")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def place_oco_order(self, oco_order: OCOOrder) -> Dict:
        params = {
            **oco_order.to_api_params(),
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/order/oco", params, method="POST")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def place_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        params = {
            "batchOrders": orders,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/batchOrders", params, method="POST")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def modify_order(self, symbol: str, order_id: str, new_quantity: Optional[float] = None, new_price: Optional[float] = None, new_stop_price: Optional[float] = None) -> Dict:
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        if new_quantity:
            params["quantity"] = f"{new_quantity:.3f}"
        if new_price:
            params["price"] = f"{new_price:.2f}"
        if new_stop_price:
            params["stopPrice"] = f"{new_stop_price:.2f}"
        data = await self._make_request("/fapi/v1/order", params, method="PUT")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def modify_multiple_orders(self, symbol: str, modifications: List[Dict[str, Any]]) -> List[Dict]:
        results = []
        for mod in modifications:
            result = await self.modify_order(
                symbol=symbol,
                order_id=mod.get("order_id"),
                new_quantity=mod.get("new_quantity"),
                new_price=mod.get("new_price"),
                new_stop_price=mod.get("new_stop_price")
            )
            results.append(result)
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_order_modify_history(self, symbol: str, order_id: str) -> List[Dict]:
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/orderAmendmentHistory", params)
        return data.get("amendments", [])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/order", params, method="DELETE")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def cancel_multiple_orders(self, symbol: str, order_ids: List[str]) -> List[Dict]:
        results = []
        for order_id in order_ids:
            result = await self.cancel_order(symbol, order_id)
            results.append(result)
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def cancel_all_open_orders(self, symbol: str) -> Dict:
        params = {
            "symbol": symbol,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/allOpenOrders", params, method="DELETE")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def query_all_orders(self, symbol: str, limit: int = 1000) -> List[Dict]:
        params = {
            "symbol": symbol,
            "limit": limit,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/allOrders", params)
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def query_current_all_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        if symbol:
            params["symbol"] = symbol
        data = await self._make_request("/fapi/v1/openOrders", params)
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def query_current_open_order(self, symbol: str, order_id: str) -> Dict:
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/order", params)
        return data if data.get("status") in ["NEW", "PARTIALLY_FILLED"] else {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def query_users_force_orders(self, symbol: Optional[str] = None, auto_close_type: Optional[str] = None) -> List[Dict]:
        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        if symbol:
            params["symbol"] = symbol
        if auto_close_type:
            params["autoCloseType"] = auto_close_type
        data = await self._make_request("/fapi/v1/forceOrders", params)
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_balance(self) -> List[Dict]:
        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        data = await self._make_request("/fapi/v2/balance", params)
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_positions(self) -> List[Dict]:
        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        data = await self._make_request("/fapi/v2/positionRisk", params)
        return [p for p in data if float(p["positionAmt"]) != 0]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def set_position_mode(self, dual_side: bool) -> None:
        params = {
            "dualSidePosition": "true" if dual_side else "false",
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        await self._make_request("/fapi/v1/positionSide/dual", params, method="POST")
        logger.debug("Set position mode: dual_side=%s", dual_side)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def set_leverage(self, symbol: str, leverage: float) -> None:
        params = {
            "symbol": symbol,
            "leverage": int(leverage),
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        await self._make_request("/fapi/v1/leverage", params, method="POST")
        logger.debug("Set leverage for %s: %d", symbol, int(leverage))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_maintenance_margin_rate(self, symbol: str) -> float:
        params = {"symbol": symbol}
        data = await self._make_request("/fapi/v1/premiumIndex", params)
        return float(data.get("maintenanceMarginRate", 0.01))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        data = await self._make_request("/fapi/v1/order", params)
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_exchange_info(self) -> Dict:
        return await self._make_request("/fapi/v1/exchangeInfo")