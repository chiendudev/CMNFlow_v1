import numpy as np
import logging
from typing import List, Dict, Tuple, Optional
try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    logging.warning("TA-Lib not available, falling back to manual calculations")

logger = logging.getLogger(__name__)

class Indicators:
    @staticmethod
    def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        """Tính RSI bằng TA-Lib hoặc thủ công."""
        if len(closes) < period:
            return 50.0
        if TALIB_AVAILABLE:
            try:
                rsi = talib.RSI(closes, timeperiod=period)
                return float(rsi[-1]) if len(rsi) > 0 else 50.0
            except Exception as e:
                logger.error(f"TA-Lib RSI error: {e}, falling back to manual")
        # Fallback thủ công
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-diff)
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period + 1e-10
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_ema(closes: np.ndarray, period: int) -> float:
        """Tính EMA bằng TA-Lib hoặc thủ công."""
        if len(closes) == 0:
            return 0.0
        if TALIB_AVAILABLE:
            try:
                ema = talib.EMA(closes, timeperiod=period)
                return float(ema[-1]) if len(ema) > 0 else float(closes[-1])
            except Exception as e:
                logger.error(f"TA-Lib EMA error: {e}, falling back to manual")
        # Fallback thủ công
        k = 2 / (period + 1)
        ema = closes[0]
        for price in closes[1:]:
            ema = price * k + ema * (1 - k)
        return ema

    @staticmethod
    def calculate_macd(closes: np.ndarray, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> tuple:
        """Tính MACD bằng TA-Lib hoặc thủ công."""
        if len(closes) < slow_period:
            return 0.0, 0.0, 0.0
        if TALIB_AVAILABLE:
            try:
                macd_line, signal_line, histogram = talib.MACD(closes, fastperiod=fast_period, slowperiod=slow_period, signalperiod=signal_period)
                return (float(macd_line[-1]) if len(macd_line) > 0 else 0.0,
                        float(signal_line[-1]) if len(signal_line) > 0 else 0.0,
                        float(histogram[-1]) if len(histogram) > 0 else 0.0)
            except Exception as e:
                logger.error(f"TA-Lib MACD error: {e}, falling back to manual")
        # Fallback thủ công
        ema_12 = np.array([Indicators.calculate_ema(closes[:i+1], 12) for i in range(12, len(closes))])
        ema_26 = np.array([Indicators.calculate_ema(closes[:i+1], 26) for i in range(26, len(closes))])
        macd_line = ema_12[-len(ema_26):] - ema_26
        signal_line = np.array([Indicators.calculate_ema(macd_line[:i+1], signal_period)
                               for i in range(signal_period, len(macd_line))])
        macd_line = macd_line[-len(signal_line):]
        histogram = macd_line - signal_line
        return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])

    @staticmethod
    def find_support_resistance(klines: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
        closes = np.array([k["close"] for k in klines])
        highs = np.array([k.get("high", k["close"]) for k in klines])
        lows = np.array([k.get("low", k["close"]) for k in klines])
        support = lows.min() if len(lows) > 0 else None
        resistance = highs.max() if len(highs) > 0 else None
        return support, resistance

    @staticmethod
    def calculate_atr(klines: List[Dict], period: int) -> float:
        highs = np.array([k.get("high", k["close"]) for k in klines])
        lows = np.array([k.get("low", k["close"]) for k in klines])
        closes = np.array([k["close"] for k in klines])
        atr = talib.ATR(highs, lows, closes, timeperiod=period)
        return atr[-1] if len(klines) >= period else 0

    @staticmethod
    def calculate_bollinger_bands(closes: np.ndarray, period: int, std_dev: float) -> Tuple[float, float, float]:
        upper, middle, lower = talib.BBANDS(closes, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev)
        return upper[-1], middle[-1], lower[-1] if len(closes) >= period else (0, 0, 0)


