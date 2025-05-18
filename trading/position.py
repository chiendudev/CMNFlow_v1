from typing import Dict
from trading.enums import PositionSide, MarginType, OrderSide
from trading.orders import NewOrder, StopOrderManager
import logging

logger = logging.getLogger(__name__)

class MarginCalculator:
    def __init__(self, leverage: float):
        self.leverage = leverage

    def check_margin(self, position, required_qty: float) -> bool:
        if not position:
            return False
        required_margin = abs(position.entry_price * required_qty) / self.leverage
        return required_margin <= position.isolated_margin

class Position:
    def __init__(self, symbol: str, position_side: PositionSide, portfolio_manager, margin_type: MarginType, leverage: float):
        self.symbol = symbol
        self.position_side = position_side
        self.portfolio_manager = portfolio_manager
        self.margin_type = margin_type
        self.leverage = leverage
        self.entry_price: float = 0.0
        self.position_amt: float = 0.0
        self.isolated_margin: float = 0.0
        self.notional: float = 0.0
        self.mark_price: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.realized_pnl: float = 0.0
        self.total_fee: float = 0.0
        self.total_funding: float = 0.0
        self.stop_order_manager = StopOrderManager(portfolio_manager.exchange_client)
        self.break_even_price: float = 0.0
        self.liquidation_price: float = 0.0
        self.margin_ratio: float = 0.0

    def _calc_pnl(self, price: float, qty: float) -> float:
        if self.position_side in [PositionSide.LONG, PositionSide.BOTH]:
            return (price - self.entry_price) * qty
        return (self.entry_price - price) * qty

    def apply_order(self, order: NewOrder):
        qty = order.executed_qty * (-1 if order.side == OrderSide.SELL else 1)
        old_position_amt = self.position_amt
        old_notional = abs(self.entry_price * old_position_amt)
        self.position_amt += qty if self.position_side == PositionSide.BOTH else abs(qty)
        new_notional = abs(order.avg_price * abs(qty))
        if order.reduce_only:
            self.isolated_margin -= abs(self.entry_price * abs(qty)) / self.leverage
            self.realized_pnl += self._calc_pnl(order.avg_price, abs(qty)) * (-1 if qty > 0 else 1)
        else:
            if self.position_amt == 0:
                self.entry_price = order.avg_price
            elif abs(old_position_amt) > 0:
                self.entry_price = (old_notional + new_notional) / abs(self.position_amt) if self.position_amt != 0 else 0
            self.isolated_margin += new_notional / self.leverage
        self.total_fee += order.fee
        self._update_market_data()

    def _update_market_data(self):
        if self.position_amt == 0:
            self.notional = 0.0
            self.unrealized_pnl = 0.0
            self.liquidation_price = 0.0
            self.break_even_price = 0.0
            self.margin_ratio = 0.0
            return
        self.notional = abs(self.mark_price * self.position_amt)
        self.unrealized_pnl = self._calc_pnl(self.mark_price, abs(self.position_amt))
        fee_impact = self.total_fee / abs(self.position_amt) if self.position_amt != 0 else 0
        self.break_even_price = self.entry_price + fee_impact if self.position_side in [PositionSide.LONG, PositionSide.BOTH] else self.entry_price - fee_impact
        margin_info = self.portfolio_manager.exchange_client.get_margin_info(self.symbol)
        mmr = margin_info["maintenance_margin_rate"]
        mm = margin_info["maintenance_amount"]
        margin_balance = self.isolated_margin + self.unrealized_pnl
        if margin_balance > 0:
            self.margin_ratio = (mmr * self.notional + mm) / margin_balance * 100
        else:
            self.margin_ratio = float('inf')
        if self.margin_type == MarginType.ISOLATED:
            if self.position_side in [PositionSide.LONG, PositionSide.BOTH]:
                self.liquidation_price = self.entry_price * (1 - 1/self.leverage + mmr)
            else:
                self.liquidation_price = self.entry_price * (1 + 1/self.leverage - mmr)

    async def set_mark_price(self, price: float):
        if price <= 0:
            logger.warning("mark_price=%.2f không hợp lệ cho %s", price, self.symbol)
            return
        self.mark_price = price
        self._update_market_data()
        await self.stop_order_manager.check_stop_orders(self, price)