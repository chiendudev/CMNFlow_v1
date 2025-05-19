import numpy as np
from typing import List, Dict, Any, Tuple


class Indicators:
    def __init__(self):
        pass

    def calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Tính Relative Strength Index (RSI)."""
        # Giả định triển khai hiện có
        deltas = np.diff(closes)
        seed = deltas[:period]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / down if down != 0 else np.inf
        return 100 - (100 / (1 + rs))

    def calculate_ema(self, closes: List[float], period: int) -> float:
        """Tính Exponential Moving Average (EMA)."""
        # Giả định triển khai hiện có
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        return np.convolve(closes, weights, mode='valid')[0]

    def calculate_atr(self, klines: List[Dict[str, Any]], period: int = 14) -> float:
        """Tính Average True Range (ATR)."""
        # Giả định triển khai hiện có
        trs = []
        for i in range(1, len(klines)):
            high = klines[i]["high"]
            low = klines[i]["low"]
            prev_close = klines[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return np.mean(trs[-period:]) if trs else 0.0

    def find_support_resistance(self, klines: List[Dict[str, Any]], window: int = 20) -> Tuple[float, float]:
        """Tìm mức hỗ trợ và kháng cự dựa trên giá thấp nhất/cao nhất trong window."""
        if len(klines) < window:
            return (klines[0]["low"], klines[0]["high"]) if klines else (0.0, 0.0)

        lows = [kline["low"] for kline in klines[:window]]
        highs = [kline["high"] for kline in klines[:window]]
        support = min(lows)
        resistance = max(highs)
        return (support, resistance)