from src.exchange.client import ExchangeClient

class ExchangeInfo:
    def __init__(self, client: ExchangeClient):
        self.client = client
        self.data = {}

    async def initial(self):
        await self.fetch_exchange_info()

    async def fetch_exchange_info(self):
        data = await self.client.get_exchange_info()
        if not data:
            raise ValueError(f"Fect exchange info error: {data}")
        if 'symbols' in data:
            for ex_info in data['symbols']:
                self.data[ex_info['symbol']] = ex_info

    def symbol_info(self, symbol):
        if symbol not in self.data:
            raise ValueError(f"")
        print(self.data[symbol])
        return self.data[symbol]