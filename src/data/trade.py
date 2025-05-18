from pydantic import BaseModel, Field

class Trade(BaseModel):
    id: int = Field(0, alias="a")
    price: float = Field(0.0, alias="p")
    qty: float = Field(0.0, alias="q")
    first_id: int = Field(0, alias="f")
    last_id: int = Field(0, alias="l")
    timestamp: int = Field(0, alias="T")
    is_maker: bool = Field(True, alias="m")

class TradeSummary(BaseModel):
    price: float
    maker_qty: float = 0.0
    taker_qty: float = 0.0
    total_qty: float = 0.0
    num_trades: int = 0
    last_update: int

    def update(self, trade: Trade) -> None:
        if trade.price != self.price:
            return
        qty = trade.qty
        if trade.is_maker:
            self.maker_qty += qty
        else:
            self.taker_qty += qty
        self.total_qty += qty
        self.num_trades += (trade.last_id + 1) - trade.first_id
        self.last_update = trade.timestamp