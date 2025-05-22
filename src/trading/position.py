from src.trading.enums import PositionSide, OrderSide
from typing import List, Dict, Any
from dataclasses import dataclass, field
from src.trading.orders import Order
@dataclass
class Position:
    symbol: str = ''
    position_side: PositionSide = PositionSide.BOTH
    position_amt: float = 0.0
    entry_price: float = 0.0
    break_even_price: float = 0.0
    mark_price: float = 0.0
    unrealized_profit: float = 0.0
    liquidation_price: float = 0.0
    isolated_margin: float = 0.0
    notional: float = 0.0
    margin_asset: str = ''
    isolated_wallet: float = 0.0
    initial_margin: float = 0.0
    maint_margin: float = 0.0
    position_initial_margin: float = 0.0
    open_order_initial_margin: float = 0.0
    adl: int = 0
    bid_notional: int = 0
    ask_notional: int = 0
    update_time: int = 0
    realized_profit: float = 0.0
    orders: List[Order] = field(default_factory=list)

    def update_price_metrics(
        self,
        mark_price: float,
        wallet_balance: float,
        leverage: float = 10.0,
        maintenance_margin_rate: float = 0.005,
        maintenance_margin_amount: float = 0.0
    ):
        """Cập nhật các chỉ số khi có giá thị trường mới."""
        self.mark_price = mark_price
        self.update_time = int(__import__('time').time() * 1000)  # Timestamp hiện tại (ms)

        # Cập nhật các chỉ số liên quan đến giá
        self._update_unrealized_profit()
        self._update_margin(leverage, maintenance_margin_rate)
        self._cal_liquidation_price(wallet_balance, maintenance_margin_rate, maintenance_margin_amount)

    def update_order_metrics(
        self,
        order: Order,
        taker_fee: float = 0.0004,  # Phí taker mặc định của Binance Futures
        step_size: str = "0.001",
        wallet_balance: float = 0.0,
        leverage: float = 10.0,
        maintenance_margin_rate: float = 0.005,
        maintenance_margin_amount: float = 0.0
    ):
        """Cập nhật các chỉ số khi có lệnh mới."""
        # Thêm lệnh mới vào danh sách orders
        self.orders.append(order)
        self.update_time = int(__import__('time').time() * 1000)  # Timestamp hiện tại (ms)

        # Cập nhật giá nhập và số lượng vị thế
        self._cal_entry_price(order.price, order.quantity, order.side.value, taker_fee)
        self.position_amt = self._cal_position_amt(step_size)

        # Cập nhật giá hòa vốn
        self._cal_break_even_price(taker_fee)

        # Cập nhật các chỉ số margin và thanh lý
        self._update_margin(leverage, maintenance_margin_rate)
        self._cal_liquidation_price(wallet_balance, maintenance_margin_rate, maintenance_margin_amount)

    def ws_update(self, data: Dict[str, Any]):
        """Cập nhật dữ liệu vị thế từ websocket."""
        # Tùy thuộc vào định dạng dữ liệu websocket của sàn
        pass

    def price_update(self, new_price: float):
        """Cập nhật giá thị trường (mark price) cho mục đích kiểm tra."""
        self._update_mark_price(price=new_price)

    def _update_mark_price(self, price: float):
        """Cập nhật giá thị trường và tính lại các chỉ số liên quan."""
        self.mark_price = price
        self._update_unrealized_profit()
        self._update_margin()

    def _update_unrealized_profit(self):
        """Tính lợi nhuận chưa thực hiện dựa trên giá thị trường và vị thế."""
        if self.position_side == PositionSide.BOTH:
            # Chế độ one-way: Lợi nhuận = position_amt * (mark_price - entry_price)
            self.unrealized_profit = self.position_amt * (self.mark_price - self.entry_price)
        else:
            # Chế độ hedge: Phụ thuộc vào LONG hay SHORT
            if self.position_side == PositionSide.LONG:
                self.unrealized_profit = self.position_amt * (self.mark_price - self.entry_price)
            else:  # SHORT
                self.unrealized_profit = self.position_amt * (self.entry_price - self.mark_price)

    def _cal_position_amt(self, step_size: str):
        """Tính tổng số lượng vị thế từ danh sách lệnh, làm tròn theo step_size."""
        sum_qty = sum(o.quantity if o.side == OrderSide.BUY else -o.quantity for o in self.orders)
        return self._floor_to_step_size(str(sum_qty), step_size)

    def _floor_to_step_size(self, value: str, step_size: str) -> float:
        """Làm tròn số lượng xuống theo step_size (độ chính xác lot size)."""
        step = float(step_size)
        return round(float(value) // step * step, len(step_size.rstrip('0').split('.')[-1]))

    def _cal_entry_price(self, price: float, qty: float, order_side: OrderSide, taker_fee: float):
        """Tính giá nhập trung bình sau khi thêm lệnh mới, theo logic Binance Futures."""
        if self.position_side == PositionSide.BOTH:  # Chế độ one-way
            current_qty = abs(self.position_amt)
            new_qty = qty
            if self.position_amt == 0:  # Chưa có vị thế
                self.entry_price = price
                self.position_amt = qty if order_side == OrderSide.BUY else -qty
            elif self.position_amt > 0:  # Vị thế LONG hiện tại
                if order_side == OrderSide.BUY:
                    # Thêm vào vị thế LONG
                    self.entry_price = (self.entry_price * current_qty + price * new_qty) / (current_qty + new_qty)
                    self.position_amt += qty
                else:  # SELL
                    if qty <= current_qty:  # Giảm hoặc đóng vị thế LONG
                        self.realized_profit += qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt -= qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:  # Đóng LONG và mở SHORT
                        self.realized_profit += current_qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt = -(qty - current_qty)
                        self.entry_price = price
            else:  # Vị thế SHORT hiện tại
                if order_side == OrderSide.SELL:
                    # Thêm vào vị thế SHORT
                    self.entry_price = (self.entry_price * current_qty + price * new_qty) / (current_qty + new_qty)
                    self.position_amt -= qty
                else:  # BUY
                    if qty <= current_qty:  # Giảm hoặc đóng vị thế SHORT
                        self.realized_profit += qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt += qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:  # Đóng SHORT và mở LONG
                        self.realized_profit += current_qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt = qty - current_qty
                        self.entry_price = price
        else:  # Chế độ hedge
            if self.position_side == PositionSide.LONG:
                if order_side == OrderSide.BUY:
                    # Thêm vào vị thế LONG
                    current_qty = self.position_amt
                    if current_qty == 0:
                        self.entry_price = price
                    else:
                        self.entry_price = (self.entry_price * current_qty + price * qty) / (current_qty + qty)
                    self.position_amt += qty
                else:  # SELL: Đóng hoặc giảm vị thế LONG
                    if qty <= self.position_amt:
                        self.realized_profit += qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt -= qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        raise ValueError("Không thể bán nhiều hơn số lượng vị thế LONG trong chế độ hedge")
            else:  # SHORT
                if order_side == OrderSide.SELL:
                    # Thêm vào vị thế SHORT
                    current_qty = abs(self.position_amt)
                    if current_qty == 0:
                        self.entry_price = price
                    else:
                        self.entry_price = (self.entry_price * current_qty + price * qty) / (current_qty + qty)
                    self.position_amt -= qty
                else:  # BUY: Đóng hoặc giảm vị thế SHORT
                    if qty <= abs(self.position_amt):
                        self.realized_profit += qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt += qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        raise ValueError("Không thể mua nhiều hơn số lượng vị thế SHORT trong chế độ hedge")

        # Cập nhật giá hòa vốn
        self._cal_break_even_price(taker_fee)

    def _cal_break_even_price(self, taker_fee: float):
        """Tính giá hòa vốn, có tính đến phí giao dịch."""
        if self.position_amt == 0:
            self.break_even_price = 0.0
        else:
            # Giá hòa vốn = entry_price ± phí giao dịch (tùy hướng vị thế)
            fee_adjustment = self.entry_price * taker_fee
            if self.position_side == PositionSide.BOTH:
                self.break_even_price = self.entry_price + fee_adjustment if self.position_amt > 0 else self.entry_price - fee_adjustment
            else:
                self.break_even_price = self.entry_price + fee_adjustment if self.position_side == PositionSide.LONG else self.entry_price - fee_adjustment

    def _update_margin(self, leverage: float = 10.0, maintenance_margin_rate: float = 0.005):
        """Cập nhật các trường margin dựa trên vị thế."""
        # Giá trị danh nghĩa (notional)
        self.notional = abs(self.position_amt) * self.mark_price
        # Margin ban đầu
        self.initial_margin = self.notional / leverage
        # Margin duy trì (theo tỷ lệ maintenance_margin_rate)
        self.maint_margin = self.notional * maintenance_margin_rate
        # Margin riêng lẻ (isolated) hoặc chéo (cross)
        if self.isolated_wallet > 0:  # Chế độ isolated
            self.isolated_margin = self.isolated_wallet
        else:  # Chế độ cross
            self.isolated_margin = 0.0
        self.position_initial_margin = self.initial_margin
        # Margin cho lệnh mở
        self._cal_open_order_initial_margin(leverage)
        # Cập nhật lợi nhuận chưa thực hiện
        self._update_unrealized_profit()

    def _cal_open_order_initial_margin(self, leverage: float):
        """Tính margin yêu cầu cho lệnh mở (bid/ask notional)."""
        # Giả định bid/ask notional dựa trên lệnh chờ trong orders
        self.bid_notional = sum(o.quantity * o.price for o in self.orders if o.side == OrderSide.BUY)
        self.ask_notional = sum(o.quantity * o.price for o in self.orders if o.side == OrderSide.SELL)
        self.open_order_initial_margin = (self.bid_notional + self.ask_notional) / leverage

    def _cal_liquidation_price(self, wallet_balance: float, maintenance_margin_rate: float = 0.005, maintenance_margin_amount: float = 0.0):
        """Tính giá thanh lý theo logic Binance Futures."""
        if self.position_amt == 0:
            self.liquidation_price = 0.0
            return

        # Tính giá trị danh nghĩa và margin duy trì
        self.notional = abs(self.position_amt) * self.mark_price
        self.maint_margin = self.notional * maintenance_margin_rate + maintenance_margin_amount

        # Số dư hiệu quả: isolated_wallet (isolated mode) hoặc wallet_balance (cross mode)
        effective_balance = self.isolated_wallet if self.isolated_wallet > 0 else wallet_balance

        # Tính lợi nhuận chưa thực hiện để điều chỉnh số dư
        self._update_unrealized_profit()
        effective_balance += self.unrealized_profit

        # Công thức giá thanh lý
        if self.position_side == PositionSide.BOTH:
            if self.position_amt > 0:  # LONG
                self.liquidation_price = self.entry_price - (effective_balance - self.maint_margin) / self.position_amt
            else:  # SHORT
                self.liquidation_price = self.entry_price + (effective_balance - self.maint_margin) / abs(self.position_amt)
        else:
            if self.position_side == PositionSide.LONG:
                self.liquidation_price = self.entry_price - (effective_balance - self.maint_margin) / self.position_amt
            else:  # SHORT
                self.liquidation_price = self.entry_price + (effective_balance - self.maint_margin) / abs(self.position_amt)

        # Đảm bảo giá thanh lý không âm
        self.liquidation_price = max(self.liquidation_price, 0.0)