# src/trading/portfolio.py

from typing import Dict, Optional
from src.trading.position import Position
from src.trading.enums import PositionSide, OrderSide, OrderType
from src.trading.orders import Order

class Portfolio:
    def __init__(self, wallet_balance: float = 0.0, hedge_mode: bool = False):
        self.wallet_balance: float = wallet_balance  # Số dư ví cross margin
        self.hedge_mode: bool = hedge_mode  # True nếu dùng Hedge Mode
        self.positions: Dict[str, Dict[PositionSide, Position]] = {}

    def apply_order(self, order: Order):
        symbol = order.symbol
        side = order.position_side
        if not order.fee:
            is_maker = order.type == OrderType.LIMIT
            order.calculate_fee(is_maker=is_maker, maker_fee=maker_fee, taker_fee=taker_fee)

        # Tính initial_margin tạm thời
        temp_pos = self.get_position(symbol, side)
        temp_notional = abs(
            temp_pos.position_amt + (order.quantity if order.side == OrderSide.BUY else -order.quantity)) * order.price
        temp_initial_margin = temp_notional / 20  # leverage=20
        if self.wallet_balance < temp_initial_margin + order.fee:
            raise ValueError(
                f"Insufficient wallet_balance ({self.wallet_balance}) for initial_margin ({temp_initial_margin}) and fee ({order.fee})")

        if self.hedge_mode:
            self.update_order(symbol=symbol, order=order, side=side)
        else:
            self.update_order(symbol=symbol, order=order, side=PositionSide.BOTH)
        pos = self.get_position(symbol, side)
        self.wallet_balance -= order.fee
        realized = pos.realized_profit
        self.wallet_balance += realized
        pos.realized_profit = 0.0

    def get_position(self, symbol: str, side: PositionSide = PositionSide.BOTH) -> Position:
        """Lấy ra hoặc khởi tạo một vị thế."""
        if symbol not in self.positions:
            self.positions[symbol] = {}
        if side not in self.positions[symbol]:
            self.positions[symbol][side] = Position(symbol=symbol, position_side=side)
        return self.positions[symbol][side]

    def update_order(
        self,
        symbol: str,
        order: Order,
        side: PositionSide,
        taker_fee: float = 0.0004,
        step_size: str = "0.001",
        leverage: float = 20.0,
        maintenance_margin_rate: float = 0.005,
        maintenance_margin_amount: float = 0.0,
    ):
        """Cập nhật portfolio khi có lệnh mới."""
        pos = self.get_position(symbol, side)
        pos.update_order_metrics(
            order=order,
            taker_fee=taker_fee,
            step_size=step_size,
            wallet_balance=self.wallet_balance,
            leverage=leverage,
            maintenance_margin_rate=maintenance_margin_rate,
            maintenance_margin_amount=maintenance_margin_amount,
        )

    def update_mark_price(
        self,
        symbol: str,
        price: float,
        leverage: float = 20.0,
        maintenance_margin_rate: float = 0.005,
        maintenance_margin_amount: float = 0.0,
    ):
        """Cập nhật giá mark cho các vị thế."""
        if symbol not in self.positions:
            return

        for side, pos in self.positions[symbol].items():
            pos.update_price_metrics(
                mark_price=price,
                wallet_balance=self.wallet_balance,
                leverage=leverage,
                maintenance_margin_rate=maintenance_margin_rate,
                maintenance_margin_amount=maintenance_margin_amount,
            )

    def get_total_unrealized_pnl(self) -> float:
        """Tổng lợi nhuận chưa thực hiện của tất cả vị thế."""
        return sum(
            pos.unrealized_profit
            for symbol_pos in self.positions.values()
            for pos in symbol_pos.values()
        )

    def get_total_maintenance_margin(self) -> float:
        """Tổng margin duy trì trên toàn bộ danh mục."""
        return sum(
            pos.maint_margin
            for symbol_pos in self.positions.values()
            for pos in symbol_pos.values()
        )

    def get_total_position_margin(self) -> float:
        """Tổng margin yêu cầu để giữ các vị thế."""
        return sum(
            pos.position_initial_margin
            for symbol_pos in self.positions.values()
            for pos in symbol_pos.values()
        )

    def get_liquidation_risk_symbols(self) -> Dict[str, Dict[PositionSide, float]]:
        """Lọc ra các symbol có nguy cơ bị thanh lý."""
        risk = {}
        for symbol, side_dict in self.positions.items():
            for side, pos in side_dict.items():
                if pos.position_amt != 0 and (
                    (pos.position_side in [PositionSide.LONG, PositionSide.BOTH] and pos.mark_price <= pos.liquidation_price)
                    or (pos.position_side == PositionSide.SHORT and pos.mark_price >= pos.liquidation_price)
                ):
                    risk.setdefault(symbol, {})[side] = pos.liquidation_price
        return risk

    def summary(self) -> Dict[str, Dict[str, float]]:
        """Tổng hợp dữ liệu danh mục theo symbol và position_side."""
        result = {}
        for symbol, side_dict in self.positions.items():
            result[symbol] = {}
            for side, pos in side_dict.items():
                key = side.name
                result[symbol][key] = {
                    "position_amt": pos.position_amt,
                    "entry_price": pos.entry_price,
                    "break_even_price": pos.break_even_price,
                    "unrealized_pnl": pos.unrealized_profit,
                    "liquidation_price": pos.liquidation_price,
                }
        return result
