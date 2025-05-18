from typing import List
import numpy as np
from src.core.custom_logging import get_logger

logger = get_logger(__name__)

class Indicators:
    def calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Tính RSI."""
        if len(closes) < period + 1:
            logger.warning("Insufficient data for RSI: got=%d, required=%d", len(closes), period + 1)
            return 50.0  # Neutral RSI
        closes = np.array(closes)
        deltas = np.diff(closes)
        gains = deltas.clip(min=0)
        losses = -deltas.clip(max=0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ema(self, closes: List[float], period: int) -> float:
        """Tính EMA."""
        if len(closes) < period:
            logger.warning("Insufficient data for EMA: got=%d, required=%d", len(closes), period)
            return closes[-1] if closes else 0.0
        closes = np.array(closes)
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        ema = np.convolve(closes, weights, mode="valid")[0]
        return ema

    def calculate_atr(self, klines: List[dict], period: int = 14) -> float:
        """Tính ATR."""
        if len(klines) < period:
            logger.warning("Insufficient data for ATR: got=%d, required=%d", len(klines), period)
            return 0.0
        trs = []
        for i in range(1, len(klines)):
            high = klines[i]["high"]
            low = klines[i]["low"]
            prev_close = klines[i-1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        atr = np.mean(trs[-period:])
        return atr