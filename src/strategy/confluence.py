from typing import List, Dict, Any, Optional
from src.core.settings import Settings
from src.strategy.indicators import Indicators
from src.core.custom_logging import get_logger, set_log_context

logger = get_logger(__name__)

class Confluence:
    def __init__(self, settings: Settings, indicators: Indicators):
        self.settings = settings
        self.indicators = indicators

    async def evaluate(self, symbol: str, timeframe: str, klines: List[Dict], funding_rate: Optional[float] = None, order_book: Optional[Dict] = None) -> Dict[str, Any]:
        """Đánh giá các điều kiện confluence để xác định tín hiệu giao dịch."""
        set_log_context(symbol=symbol, timeframe=timeframe)
        conditions = []
        direction = "none"  # buy, sell, hoặc none

        if not klines or len(klines) < max(self.settings.rsi_period, self.settings.ema_fast_period, self.settings.ema_slow_period):
            logger.warning("Insufficient kline data for confluence: got=%d", len(klines))
            return {"conditions": conditions, "is_valid": False, "direction": direction}

        closes = [kline["close"] for kline in klines]
        latest_price = closes[0]

        # Điều kiện 1: RSI
        rsi = self.indicators.calculate_rsi(closes, self.settings.rsi_period)
        if rsi < self.settings.rsi_oversold:
            conditions.append({"type": "rsi_oversold", "value": rsi, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif rsi > self.settings.rsi_overbought:
            conditions.append({"type": "rsi_overbought", "value": rsi, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 2: EMA
        ema_fast = self.indicators.calculate_ema(closes, self.settings.ema_fast_period)
        ema_slow = self.indicators.calculate_ema(closes, self.settings.ema_slow_period)
        if ema_fast > ema_slow and abs(latest_price - ema_fast) / ema_fast <= self.settings.confluence_range_pct:
            conditions.append({"type": "ema_bullish", "value": ema_fast, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif ema_fast < ema_slow and abs(latest_price - ema_slow) / ema_slow <= self.settings.confluence_range_pct:
            conditions.append({"type": "ema_bearish", "value": ema_slow, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 3: Hỗ trợ/Kháng cự
        support, resistance = self.indicators.find_support_resistance(klines)
        if abs(latest_price - support) / support <= self.settings.confluence_range_pct:
            conditions.append({"type": "near_support", "value": support, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif abs(latest_price - resistance) / resistance <= self.settings.confluence_range_pct:
            conditions.append({"type": "near_resistance", "value": resistance, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 4: Funding Rate
        if funding_rate is not None:
            if funding_rate < self.settings.funding_rate_threshold:
                conditions.append({"type": "low_funding_rate", "value": funding_rate, "direction": "buy"})
                direction = "buy" if direction == "none" or direction == "buy" else direction
            elif funding_rate > -self.settings.funding_rate_threshold:
                conditions.append({"type": "high_funding_rate", "value": funding_rate, "direction": "sell"})
                direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 5: Order Book (tùy chọn)
        if order_book and order_book.get("bids") and order_book.get("asks"):
            bid_price = max(price for price, _ in order_book["bids"])
            ask_price = min(price for price, _ in order_book["asks"])
            if abs(latest_price - bid_price) / bid_price <= self.settings.confluence_range_pct:
                conditions.append({"type": "strong_bid_support", "value": bid_price, "direction": "buy"})
                direction = "buy" if direction == "none" or direction == "buy" else direction
            elif abs(latest_price - ask_price) / ask_price <= self.settings.confluence_range_pct:
                conditions.append({"type": "strong_ask_resistance", "value": ask_price, "direction": "sell"})
                direction = "sell" if direction == "none" or direction == "sell" else direction

        # Đánh giá confluence
        is_valid = len(conditions) >= self.settings.min_confluence_count
        if is_valid:
            logger.debug("Confluence met: symbol=%s, timeframe=%s, direction=%s, conditions=%s",
                         symbol, timeframe, direction, conditions)
        else:
            logger.debug("Confluence not met: symbol=%s, timeframe=%s, conditions=%s",
                         symbol, timeframe, conditions)

        return {
            "conditions": conditions,
            "is_valid": is_valid,
            "direction": direction
        }