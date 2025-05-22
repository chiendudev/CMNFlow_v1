from src.core.settings import Settings
from src.exchange.client import ExchangeClient
from typing import Dict, Any

class UserDataApi:
    def __init__(self, setting: Settings, client: ExchangeClient):
        self.setting = setting
        self.client = client


    async def fetch_leverage_bracket(self, symbol: str):
        data = await self.client.get_leverage_bracket(symbol=symbol)
        if not data:
            raise ValueError(f'Không thể lấy thông tin leverage bracket: {data}')
        brackets = []
        for b in data:
            if b['symbol'] == symbol:
                brackets = b['brackets']
        return brackets

    async def fetch_user_commission_rate(self, symbol):
        data = await self.client.get_commission_rate(symbol)
        if not data:
            raise ValueError(f"Lấy thông tin tỉ lệ phí {symbol} không thành công")
        return data

    async def fetch_symbol_config(self, symbol: str) -> Dict[str, Any]:
        s_config: Dict[str, Any] = {}
        data = await self.client.query_symbol_config(symbol)
        if not data:
            raise ValueError(f"Fetch symbol config error: {data}")
        for s in data:
            if symbol == s['symbol']:
                s_config = s
        return s_config