from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import time
import logging
from src.trading.enums import PositionSide, OrderSide, MarginType
from src.trading.orders import Order
from src.utils.symbol_info import SymbolInfo

logger = logging.getLogger(__name__)

@dataclass
class Position:
    symbol_info: SymbolInfo
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
    bid_notional: float = 0.0
    ask_notional: float = 0.0
    update_time: int = 0
    realized_profit: float = 0.0
    orders: List[Order] = field(default_factory=list)

    def __post_init__(self):
        """Khởi tạo ban đầu và kiểm tra SymbolInfo."""
        if self.symbol_info is None or self.symbol_info.symbol != self.symbol:
            raise ValueError(f"SymbolInfo không hợp lệ hoặc không khớp với symbol {self.symbol}")
        self.margin_asset = self.symbol_info.margin_asset
        self._validate_symbol_info()

    def _validate_symbol_info(self):
        """Kiểm tra dữ liệu từ SymbolInfo."""
        required_fields = ['step_size', 'tick_size', 'taker_commission_rate', 'leverage', 'brackets']
        for field in required_fields:
            if not getattr(self.symbol_info, field):
                logger.warning(f"Trường {field} trong SymbolInfo không hợp lệ cho {self.symbol}")

    def update_price_metrics(
        self,
        mark_price: float,
        wallet_balance: float,
    ):
        """
        Cập nhật các chỉ số khi có giá thị trường mới.

        Args:
            mark_price: Giá thị trường hiện tại.
            wallet_balance: Số dư ví hiện tại.
        """
        try:
            self.mark_price = self._round_to_tick_size(mark_price)
            self.update_time = int(time.time() * 1000)
            self._update_unrealized_profit()
            self._update_margin()
            self._cal_liquidation_price(wallet_balance)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật price metrics cho {self.symbol}: {str(e)}")

    def update_order_metrics(
        self,
        order: Order,
        wallet_balance: float,
    ):
        """
        Cập nhật các chỉ số khi có lệnh mới.

        Args:
            order: Lệnh giao dịch mới.
            wallet_balance: Số dư ví hiện tại.
        """
        try:
            if order.symbol != self.symbol:
                raise ValueError(f"Lệnh không khớp với symbol {self.symbol}")
            self.orders.append(order)
            self.update_time = int(time.time() * 1000)
            self._cal_entry_price(order.price, order.quantity, order.side)
            self.position_amt = self._cal_position_amt()
            self._cal_break_even_price()
            self._update_margin()
            self._cal_liquidation_price(wallet_balance)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật order metrics cho {self.symbol}: {str(e)}")

    def ws_update(self, data: Dict[str, Any]):
        """
        Cập nhật dữ liệu vị thế từ WebSocket của Binance Futures.

        Args:
            data: Dữ liệu từ WebSocket (theo định dạng Binance).
        """
        try:
            self.mark_price = self._round_to_tick_size(float(data.get('p', self.mark_price)))
            self.position_amt = float(data.get('pa', self.position_amt))
            self.entry_price = float(data.get('ep', self.entry_price))
            self.unrealized_profit = float(data.get('up', self.unrealized_profit))
            self.isolated_wallet = float(data.get('iw', self.isolated_wallet))
            self.update_time = int(data.get('T', time.time() * 1000))
            self._update_margin()
            self._cal_liquidation_price(float(data.get('wb', 0.0)))
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật WebSocket cho {self.symbol}: {str(e)}")

    def price_update(self, new_price: float):
        """
        Cập nhật giá thị trường cho mục đích kiểm tra.

        Args:
            new_price: Giá thị trường mới.
        """
        try:
            self._update_mark_price(new_price)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật giá cho {self.symbol}: {str(e)}")

    def _update_mark_price(self, price: float):
        """Cập nhật giá thị trường và tính lại các chỉ số liên quan."""
        self.mark_price = self._round_to_tick_size(price)
        self._update_unrealized_profit()
        self._update_margin()

    def _update_unrealized_profit(self):
        """Tính lợi nhuận chưa thực hiện dựa trên giá thị trường và vị thế."""
        if self.position_amt == 0:
            self.unrealized_profit = 0.0
            return
        if self.position_side == PositionSide.BOTH:
            self.unrealized_profit = self.position_amt * (self.mark_price - self.entry_price)
        else:
            if self.position_side == PositionSide.LONG:
                self.unrealized_profit = self.position_amt * (self.mark_price - self.entry_price)
            else:  # SHORT
                self.unrealized_profit = self.position_amt * (self.entry_price - self.mark_price)

    def _cal_position_amt(self) -> float:
        """Tính tổng số lượng vị thế từ danh sách lệnh, làm tròn theo step_size."""
        sum_qty = sum(o.quantity if o.side == OrderSide.BUY else -o.quantity for o in self.orders)
        return self._floor_to_step_size(str(sum_qty), self.symbol_info.step_size)

    def _floor_to_step_size(self, value: str, step_size: str) -> float:
        """
        Làm tròn số lượng xuống theo step_size.

        Args:
            value: Giá trị cần làm tròn.
            step_size: Bước lượng từ SymbolInfo.

        Returns:
            Số lượng đã làm tròn.
        """
        try:
            step = float(step_size)
            precision = len(step_size.rstrip('0').split('.')[-1]) if '.' in step_size else 0
            return round(float(value) // step * step, precision)
        except Exception as e:
            logger.error(f"Lỗi khi làm tròn step_size: {str(e)}")
            return 0.0

    def _round_to_tick_size(self, price: float) -> float:
        """
        Làm tròn giá theo tick_size.

        Args:
            price: Giá cần làm tròn.

        Returns:
            Giá đã làm tròn.
        """
        try:
            tick = float(self.symbol_info.tick_size)
            precision = self.symbol_info.price_precision
            return round(price // tick * tick, precision)
        except Exception as e:
            logger.error(f"Lỗi khi làm tròn tick_size: {str(e)}")
            return price

    def _cal_entry_price(self, price: float, qty: float, order_side: OrderSide):
        """Tính giá nhập trung bình sau khi thêm lệnh mới."""
        taker_fee = self.symbol_info.taker_commission_rate
        price = self._round_to_tick_size(price)
        qty = self._floor_to_step_size(str(qty), self.symbol_info.step_size)

        if self.position_side == PositionSide.BOTH:
            current_qty = abs(self.position_amt)
            new_qty = qty
            if self.position_amt == 0:
                self.entry_price = price
                self.position_amt = qty if order_side == OrderSide.BUY else -qty
            elif self.position_amt > 0:
                if order_side == OrderSide.BUY:
                    self.entry_price = (self.entry_price * current_qty + price * new_qty) / (current_qty + new_qty)
                    self.position_amt += qty
                else:
                    if qty <= current_qty:
                        self.realized_profit += qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt -= qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        self.realized_profit += current_qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt = -(qty - current_qty)
                        self.entry_price = price
            else:
                if order_side == OrderSide.SELL:
                    self.entry_price = (self.entry_price * current_qty + price * new_qty) / (current_qty + new_qty)
                    self.position_amt -= qty
                else:
                    if qty <= current_qty:
                        self.realized_profit += qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt += qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        self.realized_profit += current_qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt = qty - current_qty
                        self.entry_price = price
        else:
            if self.position_side == PositionSide.LONG:
                if order_side == OrderSide.BUY:
                    current_qty = self.position_amt
                    if current_qty == 0:
                        self.entry_price = price
                    else:
                        self.entry_price = (self.entry_price * current_qty + price * qty) / (current_qty + qty)
                    self.position_amt += qty
                else:
                    if qty <= self.position_amt:
                        self.realized_profit += qty * (price - self.entry_price) * (1 - taker_fee)
                        self.position_amt -= qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        raise ValueError("Không thể bán nhiều hơn số lượng vị thế LONG trong chế độ hedge")
            else:
                if order_side == OrderSide.SELL:
                    current_qty = abs(self.position_amt)
                    if current_qty == 0:
                        self.entry_price = price
                    else:
                        self.entry_price = (self.entry_price * current_qty + price * qty) / (current_qty + qty)
                    self.position_amt -= qty
                else:
                    if qty <= abs(self.position_amt):
                        self.realized_profit += qty * (self.entry_price - price) * (1 - taker_fee)
                        self.position_amt += qty
                        if self.position_amt == 0:
                            self.entry_price = 0.0
                    else:
                        raise ValueError("Không thể mua nhiều hơn số lượng vị thế SHORT trong chế độ hedge")

    def _cal_break_even_price(self):
        """Tính giá hòa vốn, có tính đến phí giao dịch."""
        taker_fee = self.symbol_info.taker_commission_rate
        if self.position_amt == 0:
            self.break_even_price = 0.0
        else:
            fee_adjustment = self.entry_price * taker_fee
            if self.position_side == PositionSide.BOTH:
                self.break_even_price = self.entry_price + fee_adjustment if self.position_amt > 0 else self.entry_price - fee_adjustment
            else:
                self.break_even_price = self.entry_price + fee_adjustment if self.position_side == PositionSide.LONG else self.entry_price - fee_adjustment
            self.break_even_price = self._round_to_tick_size(self.break_even_price)

    def _update_margin(self):
        """Cập nhật các trường margin dựa trên vị thế."""
        try:
            leverage = self.symbol_info.leverage
            bracket = self._get_bracket()
            maint_margin_ratio = bracket.maint_margin_ratio if bracket else self.symbol_info.maint_margin_percent / 100

            self.notional = abs(self.position_amt) * self.mark_price
            self.initial_margin = self.notional / leverage
            self.maint_margin = self.notional * maint_margin_ratio
            self.position_initial_margin = self.initial_margin
            self._cal_open_order_initial_margin(leverage)

            if self.symbol_info.margin_type == MarginType.ISOLATED:
                self.isolated_margin = self.isolated_wallet
            else:
                self.isolated_margin = 0.0
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật margin cho {self.symbol}: {str(e)}")

    def _get_bracket(self) -> Optional['Bracket']:
        """
        Chọn bracket phù hợp dựa trên notional.

        Returns:
            Đối tượng Bracket hoặc None nếu không tìm thấy.
        """
        try:
            for bracket in self.symbol_info.brackets:
                if bracket.notional_floor <= self.notional <= bracket.notional_cap:
                    return bracket
            return None
        except Exception as e:
            logger.error(f"Lỗi khi chọn bracket cho {self.symbol}: {str(e)}")
            return None

    def _cal_open_order_initial_margin(self, leverage: float):
        """Tính margin yêu cầu cho lệnh mở."""
        try:
            self.bid_notional = sum(o.quantity * o.price for o in self.orders if o.side == OrderSide.BUY)
            self.ask_notional = sum(o.quantity * o.price for o in self.orders if o.side == OrderSide.SELL)
            self.open_order_initial_margin = (self.bid_notional + self.ask_notional) / leverage
        except Exception as e:
            logger.error(f"Lỗi khi tính open order margin cho {self.symbol}: {str(e)}")
            self.open_order_initial_margin = 0.0

    def _cal_liquidation_price(self, wallet_balance: float):
        """
        Tính giá thanh lý theo logic Binance Futures.

        Args:
            wallet_balance: Số dư ví hiện tại.
        """
        try:
            if self.position_amt == 0:
                self.liquidation_price = 0.0
                return

            bracket = self._get_bracket()
            maint_margin_ratio = bracket.maint_margin_ratio if bracket else self.symbol_info.maint_margin_percent / 100
            self.notional = abs(self.position_amt) * self.mark_price
            self.maint_margin = self.notional * maint_margin_ratio

            effective_balance = self.isolated_wallet if self.symbol_info.margin_type == MarginType.ISOLATED else wallet_balance
            self._update_unrealized_profit()
            effective_balance += self.unrealized_profit

            taker_fee = self.symbol_info.taker_commission_rate
            fee_adjustment = self.notional * taker_fee

            if self.position_side == PositionSide.BOTH:
                if self.position_amt > 0:
                    self.liquidation_price = self.entry_price - (effective_balance - self.maint_margin - fee_adjustment) / self.position_amt
                else:
                    self.liquidation_price = self.entry_price + (effective_balance - self.maint_margin - fee_adjustment) / abs(self.position_amt)
            else:
                if self.position_side == PositionSide.LONG:
                    self.liquidation_price = self.entry_price - (effective_balance - self.maint_margin - fee_adjustment) / self.position_amt
                else:
                    self.liquidation_price = self.entry_price + (effective_balance - self.maint_margin - fee_adjustment) / abs(self.position_amt)

            self.liquidation_price = self._round_to_tick_size(max(self.liquidation_price, 0.0))
        except Exception as e:
            logger.error(f"Lỗi khi tính giá thanh lý cho {self.symbol}: {str(e)}")
            self.liquidation_price = 0.0