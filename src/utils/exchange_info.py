from src.exchange.client import ExchangeClient

class ExchangeInfo:
    def __init__(self):
        self.data = {}

    async def fetch_exchange_info(self, exchange_client: ExchangeClient):
        data = await exchange_client.get_exchange_info()
        if 'symbols' in data:
            for ex_info in data['symbols']:
                self.data[ex_info['symbol']] = ex_info