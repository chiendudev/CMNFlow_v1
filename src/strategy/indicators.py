from typing import List, Optional
import numpy as np

class Indicators:
    def rsi(self, prices: List[float], period: int = 14) -> float:
        """Tính RSI."""
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        return 100 - (100 / (1 + rs))

    def ema(self, prices: List[float], period: int) -> float:
        """Tính EMA."""
        if not prices:
            return 0.0
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        return np.convolve(prices, weights, mode='valid')[-1] if len(prices) >= period else prices[-1]

    def atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Tính ATR (Average True Range)."""
        if len(highs) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        return np.mean(trs[-period:]) if trs else 0.0

    def find_support_resistance(self, klines: List['Kline'], window: int = 20) -> tuple[Optional[float], Optional[float]]:
        """Tìm mức hỗ trợ và kháng cự."""
        if len(klines) < window:
            return None, None
        closes = [k.close for k in klines[-window:]]
        lows = [k.low for k in klines[-window:]]
        highs = [k.high for k in klines[-window:]]
        support = min(lows)
        resistance = max(highs)
        return support, resistance