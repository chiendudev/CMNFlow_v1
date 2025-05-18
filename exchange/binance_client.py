from typing import Dict
import logging

logger = logging.getLogger(__name__)

class BinanceClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._mark_price: Dict[str, float] = {}
        logger.info("Tạo Binance client")

    async def get_mark_price(self, symbol: str, mark_price: float = None) -> float:
        return mark_price or self._mark_price.get(symbol, 100000.0)

    def set_mark_price(self, symbol: str, price: float):
        if price <= 0:
            logger.warning("mark_price=%.2f không hợp lệ cho %s", price, symbol)
            return
        self._mark_price[symbol] = price
        logger.debug("Cập nhật mark_price cho %s: %.2f", symbol, price)

    def get_funding_rate(self, symbol: str) -> float:
        return 0.0001

    def get_commission_rate(self, symbol: str, is_maker: bool = True) -> float:
        return 0.0004

    def get_margin_info(self, symbol: str) -> Dict:
        return {'maintenance_margin_rate': 0.005, 'maintenance_amount': 0.0}

    def get_price_precision(self, symbol: str) -> float:
        return 0.01 if symbol == 'ETHUSDT' else 0.1