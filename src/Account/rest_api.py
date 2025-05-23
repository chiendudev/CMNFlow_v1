import aiohttp
from typing import Dict, Any, List
from src.core.settings import Settings
from src.account.account_info import AccountInfo

class FuturesRestApi:
    """Quản lý các yêu cầu REST API cho futures."""
    def __init__(self, settings: Settings, account_info: AccountInfo):
        self.settings = settings
        self.account_info = account_info
        self.base_url = "https://fapi.binance.com"

    async def _signed_request(self, method: str, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Thực hiện yêu cầu REST API có chữ ký."""
        if params is None:
            params = {}
        async with aiohttp.ClientSession() as session:
            headers = {"X-MBX-APIKEY": self.settings.api_key}
            async with session.request(method, f"{self.base_url}{endpoint}", headers=headers, params=params) as response:
                return await response.json()

    async def get_futures_account_balance_v2(self) -> List[Dict[str, Any]]:
        """Lấy số dư tài khoản futures (V2)."""
        endpoint = "/fapi/v2/balance"
        data = await self._signed_request("GET", endpoint)
        self.account_info.update_future_balance(data)
        return data

    async def get_account_information_v2(self) -> Dict[str, Any]:
        """Lấy thông tin tài khoản (V2)."""
        endpoint = "/fapi/v2/account"
        data = await self._signed_request("GET", endpoint)
        self.account_info.update_from_account_data(data)
        return data

    async def new_future_account_transfer(self, asset: str, amount: float, type: int) -> Dict[str, Any]:
        """Tạo giao dịch chuyển khoản futures."""
        endpoint = "/sapi/v1/futures/transfer"
        params = {"asset": asset, "amount": amount, "type": type}
        return await self._signed_request("POST", endpoint, params)

    async def get_income_history(self, symbol: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Lấy lịch sử thu nhập."""
        endpoint = "/fapi/v1/income"
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._signed_request("GET", endpoint, params)

    async def toggle_bnb_burn(self, spot_bnb_burn: bool = False, interest_bnb_burn: bool = False) -> Dict[str, Any]:
        """Bật/tắt BNB burn cho giao dịch futures."""
        endpoint = "/sapi/v1/bnbBurn"
        params = {"spotBNBBurn": str(spot_bnb_burn).lower(), "interestBNBBurn": str(interest_bnb_burn).lower()}
        return await self._signed_request("POST", endpoint, params)

    async def get_bnb_burn_status(self) -> Dict[str, Any]:
        """Lấy trạng thái BNB burn."""
        endpoint = "/sapi/v1/bnbBurn"
        return await self._signed_request("GET", endpoint)