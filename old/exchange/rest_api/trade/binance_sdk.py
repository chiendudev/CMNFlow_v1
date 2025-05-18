import aiohttp
import asyncio
import time
import hmac
import hashlib
import urllib.parse
from typing import Optional, Dict, Any
from aiolimiter import AsyncLimiter


class RetryRequest(Exception):
    pass

class BinanceFuturesSDK:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        weight_limit_per_min: int = 1200,
    ):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url
        self.session = aiohttp.ClientSession()
        self.limiter = AsyncLimiter(max_rate=weight_limit_per_min, time_period=60)
        self.time_offset = 0  # auto sync

    async def close(self):
        await self.session.close()

    async def _get_server_time(self):
        try:
            data = await self._request("GET", "/fapi/v1/time", signed=False, weight=1, use_server_time=False)
            server_time = data["serverTime"]
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
        except Exception as e:
            print(f"❌ Sync server time failed: {e}")
            self.time_offset = 0

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000) + self.time_offset
        params["recvWindow"] = 5000
        query_string = urllib.parse.urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret, query_string.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> Any:
        if resp.status == 429:
            retry_after = int(resp.headers.get("Retry-After", "1"))
            print(f"⚠️ Rate limit hit. Retrying in {retry_after}s...")
            await asyncio.sleep(retry_after)
            raise RetryRequest()

        elif 500 <= resp.status < 600:
            print(f"⚠️ Server error {resp.status}. Retrying...")
            raise RetryRequest()

        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"❌ Request failed [{resp.status}]: {text}")
        return await resp.json()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        weight: int = 1,
        signed: bool = False,
        use_server_time: bool = True,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"X-MBX-APIKEY": self.api_key} if signed else {}
        params = params or {}

        if signed and use_server_time and self.time_offset == 0:
            await self._get_server_time()

        if signed:
            params = self._sign_params(params)

        for attempt in range(5):
            try:
                async with self.limiter.acquire(weight):
                    if method == "GET":
                        async with self.session.get(url, params=params, headers=headers) as resp:
                            return await self._handle_response(resp)
                    elif method == "POST":
                        async with self.session.post(url, params=params, headers=headers) as resp:
                            return await self._handle_response(resp)
                    elif method == "DELETE":
                        async with self.session.delete(url, params=params, headers=headers) as resp:
                            return await self._handle_response(resp)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")
            except RetryRequest:
                await asyncio.sleep(2 ** attempt + 0.5)
                continue
        raise Exception("❌ Max retries reached.")

    # === PUBLIC + PRIVATE API METHODS ===

    async def create_order(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/fapi/v1/order", params=data, signed=True, weight=1)

    async def cancel_order(self, symbol: str, orderId: int) -> Dict[str, Any]:
        return await self._request("DELETE", "/fapi/v1/order", params={"symbol": symbol, "orderId": orderId}, signed=True, weight=1)

    async def get_open_orders(self, symbol: str) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v1/openOrders", params={"symbol": symbol}, signed=True, weight=1)

    async def get_account_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v2/account", signed=True, weight=5)

    async def get_balance(self) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v2/balance", signed=True, weight=1)

    async def get_exchange_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v1/exchangeInfo", signed=False, weight=1)
