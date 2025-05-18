from typing import Dict, List, Optional
import logging
from dataclasses import dataclass
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from aiohttp import ClientSession
from src.core.settings import Settings
from src.core.events import EventBus, SignalEvent, MarkPriceEvent, LiquidationEvent
from src.exchange.client import ExchangeClient
from src.trading.orders import Order
from src.trading.enums import OrderSide, PositionSide, OrderStatus, OrderType

logger = logging.getLogger(__name__)

@dataclass
class Position:
    symbol: str
    side: str  # LONG/SHORT
    quantity: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    liquidation_price: float = 0.0
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0
    orders: List[Order] = None

    def update_pnl(self, mark_price: float) -> None:
        """Cập nhật P&L dựa trên mark price."""
        self.current_price = mark_price
        multiplier = 1 if self.side == "LONG" else -1
        self.unrealized_pnl = (mark_price - self.entry_price) * self.quantity * multiplier

    def update_margin(self, mark_price: float, maintenance_margin_rate: float) -> None:
        """Cập nhật initial và maintenance margin."""
        self.initial_margin = (self.quantity * self.entry_price) / self.leverage
        self.maintenance_margin = self.quantity * mark_price * maintenance_margin_rate

    def check_sl_tp(self) -> Optional[str]:
        """Kiểm tra stop-loss/take-profit, trả về hành động nếu kích hoạt."""
        if self.stop_loss and (
            (self.side == "LONG" and self.current_price <= self.stop_loss) or
            (self.side == "SHORT" and self.current_price >= self.stop_loss)
        ):
            return "CLOSE_SL"
        if self.take_profit and (
            (self.side == "LONG" and self.current_price >= self.take_profit) or
            (self.side == "SHORT" and self.current_price <= self.take_profit)
        ):
            return "CLOSE_TP"
        return None

    def update_trailing_stop(self, mark_price: float, distance: float) -> None:
        """Cập nhật trailing stop dựa trên mark price và khoảng cách."""
        if not self.trailing_stop:
            self.trailing_stop = mark_price - distance if self.side == "LONG" else mark_price + distance
        else:
            if self.side == "LONG" and mark_price - distance > self.trailing_stop:
                self.trailing_stop = mark_price - distance
            elif self.side == "SHORT" and mark_price + distance < self.trailing_stop:
                self.trailing_stop = mark_price + distance
        self.stop_loss = self.trailing_stop

class Portfolio:
    def __init__(self, settings: Settings, event_bus: EventBus, exchange_client: ExchangeClient):
        self.settings = settings
        self.event_bus = event_bus
        self.exchange_client = exchange_client
        self.positions: Dict[str, Dict[str, Position]] = {}  # {symbol: {"LONG": Position, "SHORT": Position}}
        self.balance: float = 0.0  # USDT balance
        self.max_risk_per_trade: float = settings.max_risk_per_trade
        self.trailing_stop_distance: float = settings.trailing_stop_distance
        self.leverage: float = settings.leverage
        # Đăng ký handlers
        self.event_bus.subscribe("signal", self._handle_signal, priority=5)
        self.event_bus.subscribe("mark_price", self._handle_mark_price, priority=2)
        self.event_bus.subscribe("liquidation", self._handle_liquidation, priority=3)

    async def initialize(self) -> None:
        """Khởi tạo: lấy số dư, đặt Hedging Mode, và đồng bộ vị thế."""
        await self._set_hedging_mode()
        await self._set_leverage()
        await self._update_balance()
        await self._sync_positions()
        logger.info("Portfolio initialized with balance: %.2f USDT, hedging_mode: %s, leverage: %.1f",
                    self.balance, self.settings.hedging_mode, self.leverage)

    async def _set_hedging_mode(self) -> None:
        """Bật Hedging Mode trên Binance."""
        if self.settings.hedging_mode:
            await self.exchange_client.set_position_mode(dual_side=True)
            logger.info("Enabled Hedging Mode")

    async def _set_leverage(self) -> None:
        """Đặt leverage cho tất cả symbols."""
        for symbol in self.settings.symbols:
            await self.exchange_client.set_leverage(symbol, self.leverage)
            logger.debug("Set leverage for %s: %.1f", symbol, self.leverage)

    async def _update_balance(self) -> None:
        """Lấy số dư USDT từ Binance."""
        balances = await self.exchange_client.get_balance()
        self.balance = next((float(b["balance"]) for b in balances if b["asset"] == "USDT"), 0.0)
        logger.debug("Updated balance: %.2f USDT", self.balance)

    async def _sync_positions(self) -> None:
        """Đồng bộ vị thế từ Binance."""
        positions = await self.exchange_client.get_positions()
        for pos in positions:
            symbol = pos["symbol"]
            quantity = float(pos["positionAmt"])
            side = "LONG" if quantity > 0 else "SHORT"
            if quantity != 0:
                if symbol not in self.positions:
                    self.positions[symbol] = {}
                self.positions[symbol][side] = Position(
                    symbol=symbol,
                    side=side,
                    quantity=abs(quantity),
                    entry_price=float(pos["entryPrice"]),
                    current_price=float(pos["markPrice"]),
                    leverage=float(pos["leverage"]),
                    liquidation_price=float(pos["liquidationPrice"]),
                    orders=[]
                )
                maintenance_rate = await self.exchange_client.get_maintenance_margin_rate(symbol)
                self.positions[symbol][side].update_margin(float(pos["markPrice"]), maintenance_rate)
                self.positions[symbol][side].update_pnl(float(pos["markPrice"]))
        logger.debug("Synced %d positions", sum(len(pos) for pos in self.positions.values()))

    def get_margin_ratio(self) -> float:
        """Tính Margin Ratio của toàn tài khoản."""
        total_maintenance_margin = sum(
            pos.maintenance_margin for pos_dict in self.positions.values() for pos in pos_dict.values()
        )
        total_unrealized_pnl = sum(
            pos.unrealized_pnl for pos_dict in self.positions.values() for pos in pos_dict.values()
        )
        if self.balance == 0:
            return float("inf")
        return (total_maintenance_margin + total_unrealized_pnl) / self.balance * 100

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def place_order(self, order: Order) -> bool:
        """Gửi lệnh qua Binance API."""
        try:
            if not await self._check_balance(order):
                logger.error("Insufficient balance for order: %s", order)
                return False

            response = await self.exchange_client.place_order(
                symbol=order.symbol,
                side=order.side,
                position_side=order.position_side,
                type=order.type,
                quantity=order.quantity,
                price=order.price if order.type == OrderType.LIMIT else None
            )
            order.order_id = response["orderId"]
            order.status = OrderStatus(response["status"])
            logger.info("Placed order: %s, id=%s", order, order.order_id)
            return True
        except Exception as e:
            logger.error("Failed to place order: %s, error: %s", order, e)
            return False

    async def _check_balance(self, order: Order) -> bool:
        """Kiểm tra số dư và rủi ro trước khi đặt lệnh."""
        risk_amount = order.quantity * order.price * self.max_risk_per_trade
        if risk_amount > self.balance * self.max_risk_per_trade:
            logger.warning("Order exceeds max risk: risk=%.2f, max_allowed=%.2f",
                           risk_amount, self.balance * self.max_risk_per_trade)
            return False
        return True

    async def open_position(self, signal: dict) -> bool:
        """Mở vị thế dựa trên tín hiệu, hỗ trợ hedging."""
        symbol = signal["symbol"]
        side = "LONG" if signal["type"] == "buy" else "SHORT"
        quantity = self.settings.trade_quantity
        position_side = PositionSide.LONG if side == "LONG" else PositionSide.SHORT
        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if side == "LONG" else OrderSide.SELL,
            position_side=position_side,
            type=OrderType.MARKET,
            quantity=quantity,
            price=signal["entry"],
            status=OrderStatus.NEW
        )
        if await self.place_order(order):
            if symbol not in self.positions:
                self.positions[symbol] = {}
            if side not in self.positions[symbol]:
                self.positions[symbol][side] = Position(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=signal["entry"],
                    stop_loss=signal.get("stop_loss"),
                    take_profit=signal.get("take_profit"),
                    leverage=self.leverage,
                    orders=[order]
                )
            else:
                pos = self.positions[symbol][side]
                pos.quantity += quantity
                pos.entry_price = (
                    pos.entry_price * pos.quantity + signal["entry"] * quantity
                ) / (pos.quantity + quantity)
                pos.orders.append(order)
            maintenance_rate = await self.exchange_client.get_maintenance_margin_rate(symbol)
            self.positions[symbol][side].update_margin(signal["entry"], maintenance_rate)
            logger.info("Opened position: %s, side=%s, quantity=%.4f", symbol, side, quantity)
            return True
        return False

    async def close_position(self, symbol: str, side: str, reason: str = "Manual") -> bool:
        """Đóng vị thế bằng market order."""
        if symbol not in self.positions or side not in self.positions[symbol]:
            logger.warning("No position to close for %s, side=%s", symbol, side)
            return False

        pos = self.positions[symbol][side]
        order = Order(
            symbol=symbol,
            side=OrderSide.SELL if pos.side == "LONG" else OrderSide.BUY,
            position_side=PositionSide.LONG if pos.side == "LONG" else PositionSide.SHORT,
            type=OrderType.MARKET,
            quantity=pos.quantity,
            status=OrderStatus.NEW
        )
        if await self.place_order(order):
            pos.orders.append(order)
            logger.info("Closed position: %s, side=%s, reason=%s, pnl=%.2f", symbol, side, reason, pos.unrealized_pnl)
            del self.positions[symbol][side]
            if not self.positions[symbol]:
                del self.positions[symbol]
            await self._update_balance()
            return True
        return False

    async def _handle_signal(self, event: SignalEvent) -> None:
        """Xử lý SignalEvent để mở vị thế."""
        if await self.open_position(event.signal):
            logger.debug("Processed signal for %s: %s", event.symbol, event.signal["type"])

    async def _handle_mark_price(self, event: MarkPriceEvent) -> None:
        """Cập nhật P&L, margin, và kiểm tra SL/TP dựa trên MarkPriceEvent."""
        symbol = event.symbol
        if symbol in self.positions:
            maintenance_rate = await self.exchange_client.get_maintenance_margin_rate(symbol)
            for side, pos in self.positions[symbol].items():
                pos.update_pnl(event.mark_price)
                pos.update_margin(event.mark_price, maintenance_rate)
                if pos.trailing_stop:
                    pos.update_trailing_stop(event.mark_price, self.trailing_stop_distance)

                action = pos.check_sl_tp()
                if action == "CLOSE_SL":
                    await self.close_position(symbol, side, "Stop Loss")
                elif action == "CLOSE_TP":
                    await self.close_position(symbol, side, "Take Profit")
                logger.debug("Updated position for %s, side=%s: price=%.2f, pnl=%.2f, margin_ratio=%.2f%%",
                             symbol, side, event.mark_price, pos.unrealized_pnl, self.get_margin_ratio())

    async def _handle_liquidation(self, event: LiquidationEvent) -> None:
        """Xử lý LiquidationEvent để đóng vị thế nếu margin ratio cao."""
        symbol = event.symbol
        margin_ratio = self.get_margin_ratio()
        if margin_ratio > 80 and symbol in self.positions:
            for side in list(self.positions[symbol].keys()):
                logger.warning("High margin ratio (%.2f%%), closing position: %s, side=%s", margin_ratio, symbol, side)
                await self.close_position(symbol, side, "High Margin Ratio")

    def get_position(self, symbol: str, side: str) -> Optional[Position]:
        """Lấy thông tin vị thế."""
        return self.positions.get(symbol, {}).get(side)

    def get_total_pnl(self) -> float:
        """Tính tổng P&L của tất cả vị thế."""
        return sum(
            pos.unrealized_pnl for pos_dict in self.positions.values() for pos in pos_dict.values()
        )