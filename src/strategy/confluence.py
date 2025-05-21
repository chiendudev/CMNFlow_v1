from typing import List, Dict, Any, Optional
import numpy as np
from src.core.settings import Settings
from src.strategy.indicators import Indicators
from src.strategy.trade_analyzer import TradeAnalyzer
from src.core.logging_config import get_logger, set_log_context

logger = get_logger(__name__)

class Confluence:
    def __init__(self, settings: Settings, indicators: Indicators):
        self.settings = settings
        self.indicators = indicators
        self.trade_analyzer = TradeAnalyzer(price_bins=10, velocity_window_ms=60000)

    async def evaluate(self, symbol: str, timeframe: str, klines: List[Dict], trades: List[Dict], funding_rate: Optional[float] = None, order_book: Optional[Dict] = None) -> Dict[str, Any]:
        """Đánh giá các điều kiện confluence để xác định tín hiệu giao dịch."""
        set_log_context(symbol=symbol, timeframe=timeframe)
        conditions = []
        direction = "none"
        strategy = "none"

        if not klines or len(klines) < max(self.settings.rsi_period, self.settings.ema_fast_period, self.settings.ema_slow_period):
            logger.warning("Insufficient kline data for confluence: got=%d", len(klines))
            return {"conditions": conditions, "is_valid": False, "direction": direction, "strategy": strategy}

        closes = np.array([kline["close"] for kline in klines], dtype=np.float64)
        latest_price = closes[0]
        latest_kline = klines[0]
        logger.debug("Latest price: %.2f", latest_price)

        # Tính biến động
        prices = closes[:50] if len(closes) >= 50 else closes
        volatility = (np.max(prices) - np.min(prices)) / np.mean(prices) if np.mean(prices) > 0 else 0

        # Phân tích trades
        trade_analysis = self.trade_analyzer.analyze_trades(trades, symbol, timeframe, latest_kline)
        buy_pressure = trade_analysis["buy_pressure"]
        sell_pressure = trade_analysis["sell_pressure"]
        momentum = trade_analysis["momentum"]
        trade_velocity = trade_analysis["trade_velocity"]
        recent_velocity = trade_analysis["recent_velocity"]
        price_deviation = trade_analysis["price_deviation"]
        maker_ratio = trade_analysis["maker_ratio"]
        dominant_price = trade_analysis["dominant_price"]

        # Điều chỉnh ngưỡng theo khung
        rsi_oversold = 30 if timeframe == "5m" else 40
        rsi_overbought = 70 if timeframe == "5m" else 60
        buy_sell_ratio_threshold = 1.5 if timeframe != "1h" else 2.0
        velocity_multiplier = 1.5 if timeframe == "5m" else 1.2

        # Điều kiện 1: RSI
        rsi = self.indicators.calculate_rsi(closes, self.settings.rsi_period)
        logger.debug("RSI: %.2f (oversold=%.2f, overbought=%.2f)", rsi, rsi_oversold, rsi_overbought)
        if rsi < rsi_oversold:
            conditions.append({"type": "rsi_oversold", "value": rsi, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif rsi > rsi_overbought:
            conditions.append({"type": "rsi_overbought", "value": rsi, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 2: EMA
        ema_fast = self.indicators.calculate_ema(closes, self.settings.ema_fast_period)
        ema_slow = self.indicators.calculate_ema(closes, self.settings.ema_slow_period)
        ema_diff_pct = abs(latest_price - ema_fast) / ema_fast if ema_fast else float('inf')
        logger.debug("EMA: fast=%.2f, slow=%.2f, diff_pct=%.4f", ema_fast, ema_slow, ema_diff_pct)
        if ema_fast > ema_slow and ema_diff_pct <= self.settings.confluence_range_pct:
            conditions.append({"type": "ema_bullish", "value": ema_fast, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif ema_fast < ema_slow and abs(latest_price - ema_slow) / ema_slow <= self.settings.confluence_range_pct:
            conditions.append({"type": "ema_bearish", "value": ema_slow, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 3: MACD
        macd_line, macd_signal, histogram = self.indicators.calculate_macd(closes, self.settings.ema_fast_period, self.settings.ema_slow_period, self.settings.macd_signal_period)
        logger.debug("MACD: line=%.4f, signal=%.4f, histogram=%.4f", macd_line, macd_signal, histogram)
        if macd_line > macd_signal:
            conditions.append({"type": "macd_bullish", "value": macd_line, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif macd_line < macd_signal:
            conditions.append({"type": "macd_bearish", "value": macd_line, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 4: Hỗ trợ/Kháng cự
        support, resistance = self.indicators.find_support_resistance(klines)
        support_diff_pct = abs(latest_price - support) / support if support else float('inf')
        resistance_diff_pct = abs(latest_price - resistance) / resistance if resistance else float('inf')
        logger.debug("Support=%.2f, Resistance=%.2f, support_diff_pct=%.4f, resistance_diff_pct=%.4f",
                     support, resistance, support_diff_pct, resistance_diff_pct)
        if support_diff_pct <= self.settings.confluence_range_pct:
            conditions.append({"type": "near_support", "value": support, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif resistance_diff_pct <= self.settings.confluence_range_pct:
            conditions.append({"type": "near_resistance", "value": resistance, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction
        if latest_price > resistance:
            conditions.append({"type": "breakout_above_resistance", "value": resistance, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
        elif latest_price < support:
            conditions.append({"type": "breakout_below_support", "value": support, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 5: Funding Rate
        if funding_rate is not None:
            logger.debug("Funding rate: %.6f (threshold=%.6f)", funding_rate, self.settings.funding_rate_threshold)
            if funding_rate < self.settings.funding_rate_threshold:
                conditions.append({"type": "low_funding_rate", "value": funding_rate, "direction": "buy"})
                direction = "buy" if direction == "none" or direction == "buy" else direction
            elif funding_rate > -self.settings.funding_rate_threshold:
                conditions.append({"type": "high_funding_rate", "value": funding_rate, "direction": "sell"})
                direction = "sell" if direction == "none" or direction == "sell" else direction

        # Điều kiện 6: Trade Analysis
        buy_sell_ratio = buy_pressure / (sell_pressure + 1e-10)
        if buy_sell_ratio > buy_sell_ratio_threshold and recent_velocity > trade_velocity * velocity_multiplier:
            conditions.append({"type": "scalping_buy_pressure", "value": buy_pressure, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
            strategy = "scalping" if strategy == "none" else strategy
        elif buy_sell_ratio < 1 / buy_sell_ratio_threshold and recent_velocity > trade_velocity * velocity_multiplier:
            conditions.append({"type": "scalping_sell_pressure", "value": sell_pressure, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction
            strategy = "scalping" if strategy == "none" else strategy

        if momentum > 0.001 and maker_ratio > 0.6:
            conditions.append({"type": "positive_momentum", "value": momentum, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
            strategy = "momentum" if strategy == "none" else strategy
        elif momentum < -0.001 and maker_ratio > 0.6:
            conditions.append({"type": "negative_momentum", "value": momentum, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction
            strategy = "momentum" if strategy == "none" else strategy

        dominant_diff_pct = abs(latest_price - dominant_price) / dominant_price if dominant_price else float('inf')
        if dominant_diff_pct <= self.settings.confluence_range_pct and price_deviation < 0.005:
            if buy_pressure > 0.5:
                conditions.append({"type": "volume_cluster_buy", "value": dominant_price, "direction": "buy"})
                direction = "buy" if direction == "none" or direction == "buy" else direction
                strategy = "volume_cluster" if strategy == "none" else strategy
            elif sell_pressure > 0.5:
                conditions.append({"type": "volume_cluster_sell", "value": dominant_price, "direction": "sell"})
                direction = "sell" if direction == "none" or direction == "sell" else direction
                strategy = "volume_cluster" if strategy == "none" else strategy

        if recent_velocity > trade_velocity * 2.0 and latest_price > resistance and momentum > 0.002:
            conditions.append({"type": "breakout_buy", "value": recent_velocity, "direction": "buy"})
            direction = "buy" if direction == "none" or direction == "buy" else direction
            strategy = "breakout" if strategy == "none" else strategy
        elif recent_velocity > trade_velocity * 2.0 and latest_price < support and momentum < -0.002:
            conditions.append({"type": "breakout_sell", "value": recent_velocity, "direction": "sell"})
            direction = "sell" if direction == "none" or direction == "sell" else direction
            strategy = "breakout" if strategy == "none" else strategy


        # Ưu tiên scalping
        if timeframe == "5m" and volatility > 0.01:
            conditions.append({"type": "high_volatility", "value": volatility, "direction": direction})
            strategy = "scalping"

        # Đánh giá confluence
        is_valid = len(conditions) >= self.settings.min_confluence_count
        logger.debug("Confluence result: is_valid=%s, direction=%s, strategy=%s, condition_count=%d, conditions=%s",
                     is_valid, direction, strategy, len(conditions), conditions)

        return {
            "conditions": conditions,
            "is_valid": is_valid,
            "direction": direction,
            "strategy": strategy
        }