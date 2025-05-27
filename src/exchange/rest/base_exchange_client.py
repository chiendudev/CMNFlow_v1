from aiohttp import ClientSession
from typing import Dict
from datetime import datetime
import logging
from src.core.settings import Settings
import hmac
import hashlib
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
from tenacity import retry, stop_after_attempt, wait_exponential

class BaseExchangeClient:
    def __init__(self, settings: Settings, session: ClientSession):
        self.settings = settings
        self.base_url = settings.rest_api_url
        self.session = session
        self.api_key = settings.api_key
        self.api_secret = settings.api_secret
        self.rate_limit = 2400
        self.weight_used = 0

    async def _make_request(
            self,
            endpoint: str,
            params: Dict = None,
            method: str = "GET",
            signed: bool = False
    ) -> Dict:
        params = params or {}
        headers = {}

        if signed:
            headers["X-MBX-APIKEY"] = self.api_key
            params["timestamp"] = int(datetime.now().timestamp() * 1000)
            query_string = urlencode({k: v for k, v in params.items() if v is not None})
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            params["signature"] = signature

        # Loại bỏ tất cả các tham số có giá trị None trước khi gửi request
        params = {k: v for k, v in params.items() if v is not None}

        url = f"{self.base_url}{endpoint}"

        try:
            if method == "GET":
                async with self.session.get(url, params=params, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
            elif method == "POST":
                async with self.session.post(url, data=params, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
            elif method == "PUT":
                async with self.session.put(url, data=params, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
            elif method == "DELETE":
                async with self.session.delete(url, params=params, headers=headers) as resp:
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