# trading/portfolio.py
import logging
from typing import Dict, List, Tuple
from trading.enums import TradeMode, MarginType, OrderSide, PositionSide, OrderStatus
from trading.orders import NewOrder

logger = logging.getLogger(__name__)

class PortfolioManager:
    def __init__(self, mode: TradeMode, margin_type: MarginType, leverage: int):
        self.mode = mode
        self.margin_type = margin_type
        self.leverage = leverage
        self.positions: Dict[Tuple[str, PositionSide], Dict] = {}
        self.exchange_client = None

    def set_exchange_client(self, client):
        self.exchange_client = client

    async def process_new_order(self, order: NewOrder):
        logger.debug("Xử lý lệnh mới: %s", order.__dict__)
        symbol = order.symbol
        position_side = order.position_side
        key = (symbol, position_side)
        if key not in self.positions:
            self.positions[key] = {
                "quantity": 0.0,
                "entry_price": 0.0,
                "stop_losses": [],
                "take_profits": [],
                "position_side": position_side
            }
        position = self.positions[key]
        if order.status == OrderStatus.FILLED:
            old_quantity = position["quantity"]
            if order.side == OrderSide.BUY:
                position["quantity"] += order.executed_qty
                if old_quantity == 0.0:
                    position["entry_price"] = order.avg_price
                else:
                    position["entry_price"] = (
                        position["entry_price"] * old_quantity + order.avg_price * order.executed_qty
                    ) / position["quantity"]
            else:  # SELL
                position["quantity"] -= order.executed_qty
                if position["quantity"] <= 0.0:
                    position["entry_price"] = 0.0  # Reset nếu đóng vị thế
                else:
                    position["entry_price"] = (
                        position["entry_price"] * old_quantity - order.avg_price * order.executed_qty
                    ) / position["quantity"]
            position["quantity"] = max(0, position["quantity"])
            logger.debug("Cập nhật vị thế: %s", position)
        else:
            logger.warning("Lệnh không được điền: %s", order.status)

    async def set_tp_sl(self, symbol: str, position_side: PositionSide, take_profits: List, stop_losses: List):
        key = (symbol, position_side)
        if key in self.positions:
            self.positions[key]["take_profits"] = take_profits
            self.positions[key]["stop_losses"] = stop_losses
            logger.debug("Đã thiết lập SL/TP cho %s: TP=%s, SL=%s", key, take_profits, stop_losses)
        else:
            logger.warning("Không tìm thấy vị thế cho %s", key)

    def summary(self):
        logger.info("Chế độ danh mục: %s", self.mode)
        if not self.positions:
            logger.info("Không có vị thế nào đang mở.")
            return
        for (symbol, position_side), position in self.positions.items():
            logger.info(
                "Vị thế %s (%s): Số lượng=%.4f, Giá vào lệnh=%.2f, SL=%s, TP=%s",
                symbol,
                position_side.value,
                position["quantity"],
                position["entry_price"],
                position["stop_losses"],
                position["take_profits"]
            )

    async def update_all_positions(self, price: float, symbol: str):
        for (pos_symbol, position_side), position in self.positions.items():
            if pos_symbol == symbol:
                # Cập nhật giá trị vị thế (nếu cần)
                pass