from typing import List
from pydantic import BaseModel, Field


class AggTradeModel(BaseModel):
    id: int = Field(0, alias="a")
    price: float = Field(0.0, alias="p")
    qty: float = Field(0.0, alias="q")
    first_id: int = Field(0, alias="f")
    last_id: int = Field(0, alias="l")
    timestamp: int = Field(0, alias="T")
    is_maker: bool = Field(True, alias="m")

    @classmethod
    def parse_contracts(cls, json_data: List[dict]) -> List["AggTradeModel"]:
        """Chuyển danh sách dict thành danh sách AggTradeModel"""
        return [cls.model_validate(item) for item in json_data]

class AggTradesSum(BaseModel):
    first_id: int = 0
    last_id: int = 0
    price: float = 0.0
    maker_qty: float = 0.0
    taker_qty: float = 0.0
    total_qty: float = 0.0
    num_trades: int = 0
    last_update: int = 0

    def update(self, trade: AggTradeModel):
        if self.price == 0.0:
            # Nếu lần đầu tiên, gán giá
            self.price = trade.price
            self.first_id = trade.id

        if trade.price != self.price:
            # Không khớp giá, bỏ qua (hoặc raise nếu muốn)
            return

        qty = trade.qty
        if trade.is_maker:
            self.maker_qty += qty
        else:
            self.taker_qty += qty

        self.total_qty += qty
        self.num_trades += (trade.last_id + 1) - trade.first_id
        self.last_id = trade.id
        self.last_update = trade.timestamp


class KlineModel(BaseModel):
    open_time: int = 0
    close_time: int = 0
    open: float = 0.0
    close: float = 0.0
    low: float = 0.0
    high: float = 0.0
    volume: float = 0.0
    quote_volume: float = 0.0
    num_trades: int = 0
    taker_buy_base_asset_volume: float = 0.0
    taker_buy_quote_asset_volume: float = 0.0
    recent_trades: List[AggTradesSum] = Field(default_factory=list)
    is_close: bool = True
