# technical.py
from typing import List, Dict, Tuple, Optional
from config.settings import Settings
from analysis.zones import ZoneAnalyzer
from analysis.signals import SignalGenerator
import logging
import numpy as np
import talib

from logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


class TechnicalIndicators:
    def __init__(self, kline, settings: Settings):
        self.kline = kline
        self.settings = settings
        self.zone_analyzer = ZoneAnalyzer(self, settings)
        self.signal_generator = SignalGenerator(self, settings)
        self.rsi: Optional[float] = None
        self.atr: Optional[float] = None
        self.ema_fast: Optional[float] = None
        self.ema_slow: Optional[float] = None
        self._cache: Dict[str, Tuple[float, int]] = {}  # Cache: {indicator: (value, timestamp_ms)}

    def calculate(self):
        if not self.kline.close_history:
            logger.warning("Không có dữ liệu giá đóng để tính toán chỉ số kỹ thuật")
            return
        current_time = self.kline.agg_trades[-1]["timestamp_ms"] if self.kline.agg_trades else 0

        # Chuyển đổi danh sách giá thành mảng NumPy
        close_prices = np.array(self.kline.close_history, dtype=np.float64)
        high_prices = np.array(self.kline.high_history, dtype=np.float64)
        low_prices = np.array(self.kline.low_history, dtype=np.float64)

        # Tính toán RSI
        if "rsi" not in self._cache or self._cache["rsi"][1] != current_time:
            self.rsi = self._calculate_rsi(close_prices)
            self._cache["rsi"] = (self.rsi, current_time)

        # Tính toán ATR
        if "atr" not in self._cache or self._cache["atr"][1] != current_time:
            self.atr = self._calculate_atr(high_prices, low_prices, close_prices)
            self._cache["atr"] = (self.atr, current_time)

        # Tính toán EMA nhanh
        if "ema_fast" not in self._cache or self._cache["ema_fast"][1] != current_time:
            self.ema_fast = self._calculate_ema(close_prices, self.settings.ema_fast_period)
            self._cache["ema_fast"] = (self.ema_fast, current_time)

        # Tính toán EMA chậm
        if "ema_slow" not in self._cache or self._cache["ema_slow"][1] != current_time:
            self.ema_slow = self._calculate_ema(close_prices, self.settings.ema_slow_period)
            self._cache["ema_slow"] = (self.ema_slow, current_time)

        logger.debug(
            "Chỉ số kỹ thuật: RSI=%.2f, ATR=%.2f, EMA nhanh=%.2f, EMA chậm=%.2f",
            self.rsi or np.nan, self.atr or np.nan, self.ema_fast or np.nan, self.ema_slow or np.nan
        )

    def _calculate_rsi(self, close_prices: np.ndarray) -> Optional[float]:
        """Tính RSI bằng TA-Lib."""
        if len(close_prices) < self.settings.rsi_period:
            logger.warning("Không đủ dữ liệu cho RSI: %d/%d nến", len(close_prices), self.settings.rsi_period)
            return None
        try:
            rsi = talib.RSI(close_prices, timeperiod=self.settings.rsi_period)
            return float(rsi[-1]) if rsi[-1] is not np.nan else None
        except Exception as e:
            logger.error("Lỗi khi tính RSI: %s", e)
            return None

    def _calculate_atr(self, high_prices: np.ndarray, low_prices: np.ndarray, close_prices: np.ndarray) -> Optional[
        float]:
        """Tính ATR bằng TA-Lib."""
        if len(high_prices) < self.settings.atr_period or len(low_prices) < self.settings.atr_period or len(
                close_prices) < self.settings.atr_period:
            logger.warning("Không đủ dữ liệu cho ATR: %d/%d nến", len(high_prices), self.settings.atr_period)
            return None
        try:
            atr = talib.ATR(high_prices, low_prices, close_prices, timeperiod=self.settings.atr_period)
            return float(atr[-1]) if atr[-1] is not np.nan else None
        except Exception as e:
            logger.error("Lỗi khi tính ATR: %s", e)
            return None

    def _calculate_ema(self, close_prices: np.ndarray, period: int) -> Optional[float]:
        """Tính EMA bằng TA-Lib."""
        if len(close_prices) < period:
            logger.warning("Không đủ dữ liệu cho EMA (%d kỳ): %d/%d nến", period, len(close_prices), period)
            return None
        try:
            ema = talib.EMA(close_prices, timeperiod=period)
            return float(ema[-1]) if ema[-1] is not np.nan else None
        except Exception as e:
            logger.error("Lỗi khi tính EMA (%d kỳ): %s", period, e)
            return None

    def analyze_zones(self, timeframe: str) -> Tuple[List[Dict], float, int, float, List[float]]:
        return self.zone_analyzer.analyze(timeframe)

    def generate_signals(self, timeframe: str, confluence_zones: List[Dict]) -> List[Dict]:
        return self.signal_generator.generate(timeframe, confluence_zones)

    def detect_stop_hunt(self, timeframe: str, sensitive_prices: List[float]) -> Optional[Dict]:
        return self.signal_generator.detect_stop_hunt(timeframe, sensitive_prices)