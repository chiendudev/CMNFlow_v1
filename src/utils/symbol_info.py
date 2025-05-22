from src.exchange.client import ExchangeClient
from src.utils.exchange_info import ExchangeInfo
from src.utils.user_data_api import UserDataApi
from src.trading.enums import MarginType, OrderType, TimeInForce
from typing import Dict, Any, List
from dataclasses import dataclass, field

@dataclass
class Bracket:
    bracket: int = 0
    initial_leverage: int = 0
    notional_cap: float = 0.0
    notional_floor: float = 0.0
    maint_margin_ratio: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'bracket': self.bracket,
            'initialLeverage': self.initial_leverage,
            'notionalCap': self.notional_cap,
            'notionalFloor': self.notional_floor,
            'maintMarginRatio': self.maint_margin_ratio
        }

class SymbolInfo:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.base_asset: str = ''
        self.quote_asset: str = ''
        self.margin_asset: str = ''
        self.maint_margin_percent: float = 0.0  # mức kí quỹ tối thiểu để tránh bị thanh lý
        self.required_margin_percent: float = 0.0
        self.price_precision: int = 0
        self.quantity_precision: int = 0
        self.base_asset_precision: int = 0
        self.quote_precision: int = 0
        self.min_price: float = 0.0
        self.max_price: float = 0.0
        self.tick_size: str = ''
        self.min_qty: float = 0.0
        self.step_size: str = ''
        self.max_qty: float = 0.0
        self.min_notional: float = 0.0
        self.multiplier_down: float = 0.0
        self.multiplier_decimal: int = 0
        self.multiplier_up: float = 0.0
        self.order_types: List[str] = []
        self.time_in_force: List[str] = []
        self.permission_sets: List[str] = []
        self.margin_type: MarginType = MarginType.CROSSED
        self.is_auto_add_margin: bool = False
        self.leverage: int = 0
        self.max_notional_value: float = 0
        self.maker_commission_rate: float = 0.0
        self.taker_commission_rate: float = 0.0
        self.brackets: List[Bracket] = []


    async def initial_symbol_info(self,exchange_info: ExchangeInfo, user_api: UserDataApi):
        symbol_config = await user_api.fetch_symbol_config(self.symbol)
        symbol_info = exchange_info.symbol_info(self.symbol)
        bracket_arr = await user_api.fetch_leverage_bracket(self.symbol)
        commission_rate = await user_api.fetch_user_commission_rate(symbol=self.symbol)
        self.symbol_commission_rate(commission_rate)
        self.symbol_brackets(bracket_arr)
        self.symbol_info(symbol_info)
        self.symbol_configuration(symbol_config)
        pass

    def symbol_configuration(self, data: Dict[str, Any]):
        self.margin_type = MarginType.CROSSED if data['marginType'] == MarginType.CROSSED.value else MarginType.ISOLATED
        self.is_auto_add_margin = False if data['isAutoAddMargin'] == 'false' else True
        self.leverage = int(data['leverage'])
        self.max_notional_value = float(data['maxNotionalValue'])

    def symbol_info(self, data: Dict[str, Any]):
        price_filter = next((f for f in data["filters"] if f["filterType"] == "PRICE_FILTER"), None)
        lot_size = next((f for f in data["filters"] if f["filterType"] == "LOT_SIZE"), None)
        min_notional = next((f for f in data["filters"] if f["filterType"] == "MIN_NOTIONAL"), None)
        percent_price = next((f for f in data["filters"] if f["filterType"] == "PERCENT_PRICE"), None)
        self.base_asset = data['baseAsset']
        self.quote_asset = data['quoteAsset']
        self.margin_asset = data['marginAsset']
        self.maint_margin_percent = float(data['maintMarginPercent'])
        self.required_margin_percent = float(data['requiredMarginPercent'])
        self.price_precision = int(data['pricePrecision'])
        self.quantity_precision = int(data['quantityPrecision'])
        self.base_asset_precision = int(data['baseAssetPrecision'])
        self.quote_precision = int(data['quotePrecision'])
        self.min_price = float(price_filter['minPrice'])
        self.max_price = float(price_filter['maxPrice'])
        self.tick_size = price_filter['tickSize']
        self.min_qty = float(lot_size['minQty'])
        self.step_size = lot_size['stepSize']
        self.max_qty = float(lot_size['maxQty'])
        self.min_notional = float(min_notional['notional'])
        self.multiplier_down = float(percent_price['multiplierDown'])
        self.multiplier_decimal = int(percent_price['multiplierDecimal'])
        self.multiplier_up = float(percent_price['multiplierUp'])
        self.order_types = data['orderTypes']
        self.time_in_force = data['timeInForce']
        self.permission_sets = data['permissionSets']


    def symbol_brackets(self, data):
        if not data:
            raise ValueError(f"Dữ liệu bracket cho {self.symbol} không khả dụng")
        for bracket_dict in data:
            bracket = Bracket(
                bracket=int(bracket_dict['bracket']),
                initial_leverage=int(bracket_dict['initialLeverage']),
                notional_cap=float(bracket_dict['notionalCap']),
                notional_floor=float(bracket_dict['notionalFloor']),
                maint_margin_ratio=float(bracket_dict['maintMarginRatio'])
            )
            self.brackets.append(bracket)

    def symbol_commission_rate(self, data: Dict[str, Any]):
        self.maker_commission_rate = float(data['makerCommissionRate'])
        self.taker_commission_rate = float(data['takerCommissionRate'])

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "margin_asset": self.margin_asset,
            "maint_margin_percent": self.maint_margin_percent,
            "required_margin_percent": self.required_margin_percent,
            "price_precision": self.price_precision,
            "quantity_precision": self.quantity_precision,
            "base_asset_precision": self.base_asset_precision,
            "quote_precision": self.quote_precision,
            "tick_size": self.tick_size,
            "min_qty": self.min_qty,
            "step_size": self.step_size,
            "max_qty": self.max_qty,
            "min_notional": self.min_notional,
            "margin_type": self.margin_type.name,  # Chuyển Enum thành string
            "is_auto_add_margin": self.is_auto_add_margin,
            "leverage": self.leverage,
            "max_notional_value": self.max_notional_value,
            "maker_commission_rate": self.maker_commission_rate,
            "taker_commission_rate": self.taker_commission_rate,
            "brackets": [b.to_dict() for b in self.brackets]  # Gọi to_dict trên mỗi bracket
        }
