import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from src.core.logging_config import get_logger, set_log_context

logger = get_logger(__name__)

class TradeAnalyzer:
    def __init__(self, price_bins: int = 10, velocity_window_ms: int = 60000):
        """Khởi tạo TradeAnalyzer.

        Args:
            price_bins: Số lượng mức giá để phân tích phân phối khối lượng.
            velocity_window_ms: Cửa sổ thời gian (ms) để tính tốc độ giao dịch.
        """
        self.price_bins = price_bins
        self.velocity_window_ms = velocity_window_ms

    def analyze_trades(self, trades: Optional[List[Dict[str, Any]]], symbol: str, timeframe: str, kline: Dict[str, Any]) -> Dict[str, Any]:
        """Phân tích chi tiết danh sách giao dịch.

        Args:
            trades: Danh sách giao dịch từ Kline.
            symbol: Cặp giao dịch (e.g., BTCUSDT).
            timeframe: Khung thời gian (e.g., 5m).
            kline: Thông tin nến (open, high, low, close, volume).

        Returns:
            Dict chứa các chỉ số: buy_pressure, sell_pressure, price_deviation, trade_velocity,
            volume_distribution, maker_ratio, momentum, direction.
        """
        set_log_context(symbol=symbol, timeframe=timeframe)
        if not trades or not kline:
            logger.debug("No trade data or kline provided")
            return {
                "buy_pressure": 0.0,
                "sell_pressure": 0.0,
                "price_deviation": 0.0,
                "trade_velocity": 0.0,
                "volume_distribution": [],
                "maker_ratio": 0.0,
                "momentum": 0.0,
                "direction": "none"
            }

        # Chuẩn bị dữ liệu
        prices = np.array([trade["price"] for trade in trades])
        quantities = np.array([trade["quantity"] for trade in trades])
        timestamps = np.array([trade["timestamp"] for trade in trades])
        is_buyer_maker = np.array([trade["is_buyer_maker"] for trade in trades])

        # 1. Áp lực mua/bán
        buy_volume = quantities[is_buyer_maker].sum()
        sell_volume = quantities[~is_buyer_maker].sum()
        total_volume = buy_volume + sell_volume
        buy_pressure = buy_volume / total_volume if total_volume > 0 else 0.0
        sell_pressure = sell_volume / total_volume if total_volume > 0 else 0.0

        # 2. Độ lệch giá
        close_price = kline["close"]
        price_deviation = np.abs(prices - close_price).mean() / close_price if close_price > 0 else 0.0

        # 3. Tốc độ giao dịch
        duration_ms = kline["close_time"] - kline["open_time"]
        if duration_ms > 0:
            trade_velocity = len(trades) / (duration_ms / 1000.0)  # giao dịch/giây
            # Tính tốc độ cuối nến
            recent_trades = timestamps >= (kline["close_time"] - self.velocity_window_ms)
            recent_velocity = np.sum(recent_trades) / (self.velocity_window_ms / 1000.0)
        else:
            trade_velocity = recent_velocity = 0.0

        # 4. Phân phối khối lượng
        price_range = kline["high"] - kline["low"]
        if price_range > 0:
            bins = np.linspace(kline["low"], kline["high"], self.price_bins + 1)
            volume_hist = np.histogram(prices, bins=bins, weights=quantities)[0]
            volume_distribution = volume_hist / total_volume if total_volume > 0 else np.zeros(self.price_bins)
            dominant_price_bin = np.argmax(volume_hist)
            dominant_price = (bins[dominant_price_bin] + bins[dominant_price_bin + 1]) / 2
        else:
            volume_distribution = np.zeros(self.price_bins)
            dominant_price = close_price

        # 5. Tỷ lệ maker/taker
        maker_trades = np.sum(is_buyer_maker)
        maker_ratio = maker_trades / len(trades) if len(trades) > 0 else 0.0

        # 6. Xung lượng (Volume-Weighted Price Momentum)
        time_normalized = (timestamps - timestamps.min()) / (timestamps.max() - timestamps.min() + 1)
        weighted_prices = prices * quantities
        momentum = np.sum(weighted_prices * (time_normalized - 0.5)) / total_volume if total_volume > 0 else 0.0
        momentum = momentum / close_price if close_price > 0 else 0.0  # Chuẩn hóa theo giá đóng

        # Xác định direction
        direction = "none"
        if buy_pressure > sell_pressure + 0.1 and momentum > 0.001:
            direction = "buy"
        elif sell_pressure > buy_pressure + 0.1 and momentum < -0.001:
            direction = "sell"

        result = {
            "buy_pressure": buy_pressure,
            "sell_pressure": sell_pressure,
            "price_deviation": price_deviation,
            "trade_velocity": trade_velocity,
            "recent_velocity": recent_velocity,
            "volume_distribution": volume_distribution.tolist(),
            "dominant_price": dominant_price,
            "maker_ratio": maker_ratio,
            "momentum": momentum,
            "direction": direction
        }

        logger.debug("Trade analysis: buy_pressure=%.2f, sell_pressure=%.2f, price_deviation=%.4f, "
                     "trade_velocity=%.2f, recent_velocity=%.2f, maker_ratio=%.2f, momentum=%.4f, direction=%s",
                     buy_pressure, sell_pressure, price_deviation, trade_velocity, recent_velocity,
                     maker_ratio, momentum, direction)
        return result