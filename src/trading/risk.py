import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential
from src.core.settings import Settings
from src.core.events import EventBus, RiskEvent
from src.core.storage import Storage

from src.core.events import MarkPriceEvent
from src.trading.portfolio import Portfolio, Position
from src.trading.orders import Order, OCOOrder
from src.trading.enums import OrderSide, PositionSide
from src.data.kline import Kline

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, settings: Settings, event_bus: EventBus, portfolio: Portfolio, storage: Storage):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.storage = storage
        self.max_risk_per_trade = settings.max_risk_per_trade
        self.max_margin_ratio = settings.max_margin_ratio
        self.correlation_threshold = settings.correlation_threshold
        self.volatility_threshold = settings.volatility_threshold
        self.atr_period = settings.atr_period
        self.sl_atr_multiplier = settings.sl_atr_multiplier
        self.tp_atr_multiplier = settings.tp_atr_multiplier
        self.trailing_stop_distance = settings.trailing_stop_distance
        self.event_bus.subscribe("mark_price", self._handle_mark_price, priority=3)
        logger.info("Initialized RiskManager with max_risk=%.2f%%, max_margin_ratio=%.2f%%",
                    self.max_risk_per_trade * 100, self.max_margin_ratio * 100)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def calculate_atr(self, symbol: str, timeframe: str, period: int = 14) -> float:
        """Tính Average True Range (ATR) từ kline lịch sử."""
        klines = self.storage.get_klines(symbol, timeframe, limit=period + 1)
        if len(klines) < period:
            logger.warning("Insufficient klines for ATR calculation: %s, timeframe=%s", symbol, timeframe)
            return 0.0

        tr_list = []
        for i in range(1, len(klines)):
            high = klines[i].high
            low = klines[i].low
            prev_close = klines[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        atr = np.mean(tr_list[-period:]) if tr_list else 0.0
        logger.debug("Calculated ATR for %s: %.2f", symbol, atr)
        return atr

    def calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float) -> float:
        """Tính kích thước vị thế dựa trên rủi ro và ATR."""
        atr = self.calculate_atr(symbol, self.settings.base_timeframe, self.atr_period)
        if atr == 0:
            logger.error("Cannot calculate position size: ATR is zero")
            return 0.0

        risk_amount = self.portfolio.balance * self.max_risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            logger.error("Invalid stop loss: risk per unit is zero")
            return 0.0

        position_size = risk_amount / risk_per_unit
        volatility_factor = self._get_volatility_factor(symbol)
        adjusted_size = position_size / volatility_factor

        # Giới hạn kích thước vị thế theo số dư và leverage
        max_size = (self.portfolio.balance * self.settings.leverage) / entry_price
        final_size = min(adjusted_size, max_size)

        logger.debug("Calculated position size for %s: %.4f (risk_amount=%.2f, volatility_factor=%.2f)",
                     symbol, final_size, risk_amount, volatility_factor)
        return final_size

    def _get_volatility_factor(self, symbol: str) -> float:
        """Tính hệ số điều chỉnh dựa trên biến động (dùng Bollinger Bands)."""
        klines = self.storage.get_klines(symbol, self.settings.base_timeframe, limit=20)
        if len(klines) < 20:
            return 1.0

        closes = np.array([kline.close for kline in klines])
        sma = np.mean(closes)
        std = np.std(closes)
        bandwidth = (std * 2) / sma  # Bollinger Band width
        if bandwidth > self.volatility_threshold:
            return 1.5  # Giảm kích thước vị thế khi biến động cao
        elif bandwidth < self.volatility_threshold / 2:
            return 0.8  # Tăng kích thước vị thế khi biến động thấp
        return 1.0

    def calculate_sl_tp(self, symbol: str, entry_price: float, side: str) -> Tuple[float, float]:
        """Tính Stop Loss và Take Profit dựa trên ATR."""
        atr = self.calculate_atr(symbol, self.settings.base_timeframe, self.atr_period)
        if atr == 0:
            logger.error("Cannot calculate SL/TP: ATR is zero")
            return entry_price, entry_price

        if side == "LONG":
            stop_loss = entry_price - atr * self.sl_atr_multiplier
            take_profit = entry_price + atr * self.tp_atr_multiplier
        else:  # SHORT
            stop_loss = entry_price + atr * self.sl_atr_multiplier
            take_profit = entry_price - atr * self.tp_atr_multiplier

        logger.debug("Calculated SL/TP for %s (%s): SL=%.2f, TP=%.2f", symbol, side, stop_loss, take_profit)
        return stop_loss, take_profit

    def update_trailing_stop(self, position: Position, current_price: float) -> Optional[float]:
        """Cập nhật Trailing Stop dựa trên giá hiện tại."""
        if not position.trailing_stop:
            position.trailing_stop = (
                current_price - self.trailing_stop_distance if position.side == "LONG"
                else current_price + self.trailing_stop_distance
            )
        else:
            if position.side == "LONG" and current_price - self.trailing_stop_distance > position.trailing_stop:
                position.trailing_stop = current_price - self.trailing_stop_distance
            elif position.side == "SHORT" and current_price + self.trailing_stop_distance < position.trailing_stop:
                position.trailing_stop = current_price + self.trailing_stop_distance

        if position.trailing_stop != position.stop_loss:
            position.stop_loss = position.trailing_stop
            logger.debug("Updated trailing stop for %s (%s): %.2f", position.symbol, position.side,
                         position.trailing_stop)
            return position.trailing_stop
        return None

    def check_correlation_risk(self, symbol: str) -> bool:
        """Kiểm tra rủi ro tương quan giữa các cặp."""
        if not self.settings.symbols or len(self.settings.symbols) < 2:
            return True

        klines_dict = {
            sym: self.storage.get_klines(sym, self.settings.base_timeframe, limit=50)
            for sym in self.settings.symbols
        }
        if not all(len(klines) >= 50 for klines in klines_dict.values()):
            logger.warning("Insufficient klines for correlation check")
            return True

        closes = {sym: np.array([k.close for k in klines]) for sym, klines in klines_dict.items()}
        correlations = {}
        for other_sym in self.settings.symbols:
            if other_sym != symbol and other_sym in self.portfolio.positions:
                corr = np.corrcoef(closes[symbol], closes[other_sym])[0, 1]
                correlations[other_sym] = corr
                if corr > self.correlation_threshold:
                    logger.warning("High correlation between %s and %s: %.2f", symbol, other_sym, corr)
                    return False

        logger.debug("Correlation check for %s: %s", symbol, correlations)
        return True

    async def check_risk(self, order: Order, oco_order: Optional[OCOOrder] = None) -> Tuple[bool, str]:
        """Kiểm tra rủi ro trước khi đặt lệnh."""
        try:
            # Kiểm tra số dư
            risk_amount = order.quantity * (order.price or order.stop_price or 0.0)
            if risk_amount > self.portfolio.balance * self.max_risk_per_trade:
                return False, f"Order exceeds max risk: {risk_amount:.2f} > {self.portfolio.balance * self.max_risk_per_trade:.2f}"

            # Kiểm tra margin ratio
            margin_ratio = self.portfolio.get_margin_ratio()
            if margin_ratio > self.max_margin_ratio:
                await self.event_bus.publish("risk", RiskEvent(
                    type="high_margin_ratio",
                    symbol=order.symbol,
                    data={"margin_ratio": margin_ratio},
                    timestamp=int(datetime.now().timestamp() * 1000)
                ))
                return False, f"Margin ratio too high: {margin_ratio:.2f}% > {self.max_margin_ratio:.2f}%"

            # Kiểm tra funding rate
            funding_rate = await self._get_latest_funding_rate(order.symbol)
            if funding_rate > self.settings.funding_rate_threshold:
                return False, f"Funding rate too high: {funding_rate:.6f} > {self.settings.funding_rate_threshold:.6f}"

            # Kiểm tra correlation risk
            if not self.check_correlation_risk(order.symbol):
                return False, "High correlation risk with existing positions"

            # Kiểm tra OCO order
            if oco_order:
                if not oco_order.validate():
                    return False, "Invalid OCO order"
                if oco_order.quantity != order.quantity:
                    return False, "OCO order quantity mismatch"

            logger.debug("Risk check passed for order: %s", order)
            return True, "Risk check passed"
        except Exception as e:
            logger.error("Risk check failed: %s", e)
            return False, f"Risk check error: {str(e)}"

    async def _get_latest_funding_rate(self, symbol: str) -> float:
        """Lấy funding rate mới nhất từ Storage."""
        with sqlite3.connect(self.storage.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT rate FROM funding_rate 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (symbol,))
            row = cursor.fetchone()
            return float(row[0]) if row else 0.0

    async def reduce_position_if_needed(self, symbol: str, side: str) -> bool:
        """Giảm vị thế nếu margin ratio quá cao."""
        margin_ratio = self.portfolio.get_margin_ratio()
        if margin_ratio > self.max_margin_ratio:
            position = self.portfolio.get_position(symbol, side)
            if position:
                reduce_quantity = position.quantity * 0.5  # Giảm 50% vị thế
                order = Order(
                    symbol=symbol,
                    side=OrderSide.SELL if side == "LONG" else OrderSide.BUY,
                    position_side=PositionSide.LONG if side == "LONG" else PositionSide.SHORT,
                    type=OrderType.MARKET,
                    quantity=reduce_quantity,
                    reduce_only=True
                )
                if await self.portfolio.place_order(order):
                    logger.info("Reduced position for %s (%s) by %.4f due to high margin ratio",
                                symbol, side, reduce_quantity)
                    await self.event_bus.publish("risk", RiskEvent(
                        type="position_reduced",
                        symbol=symbol,
                        data={"side": side, "quantity": reduce_quantity},
                        timestamp=int(datetime.now().timestamp() * 1000)
                    ))
                    return True
            return False
        return True

    async def _handle_mark_price(self, event: MarkPriceEvent) -> None:
        """Cập nhật trailing stop và kiểm tra margin ratio."""
        symbol = event.symbol
        current_price = event.mark_price
        if symbol in self.portfolio.positions:
            for side, position in self.portfolio.positions[symbol].items():
                # Cập nhật trailing stop
                new_stop = self.update_trailing_stop(position, current_price)
                if new_stop:
                    self.storage.save_position(position)

                # Kiểm tra và giảm vị thế nếu cần
                await self.reduce_position_if_needed(symbol, side)
                logger.debug("Processed mark price for %s (%s): price=%.2f, margin_ratio=%.2f%%",
                             symbol, side, current_price, self.portfolio.get_margin_ratio())