from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    def __init__(self, market_data, settings: Optional[Dict] = None):
        """
        Initialize TrendAnalyzer for real-world trading.

        Args:
            market_data: Dictionary of OHLCV DataFrames for multiple timeframes:
                {
                    '1m': pd.DataFrame,
                    '5m': pd.DataFrame,
                    '15m': pd.DataFrame,
                    '1h': pd.DataFrame,
                    ...
                }
                Each DataFrame has columns: ['open', 'high', 'low', 'close', 'volume']
            settings: Optional configuration dictionary with thresholds:
                {
                    'rsi_period': int,  # Default 14
                    'ema_short': int,  # Default 20
                    'ema_mid': int,    # Default 50
                    'ema_long': int,   # Default 200
                    'adx_period': int, # Default 14
                    'adx_threshold': float,  # Default 25
                    'rsi_bullish': float,   # Default 55
                    'rsi_bearish': float,   # Default 45
                    'atr_period': int,      # Default 14
                    'atr_threshold_pct': float  # Default 0.001 (0.1% of price)
                }
        """
        self.market_data = market_data
        self.settings = settings or {
            'rsi_period': 14,
            'ema_short': 20,
            'ema_mid': 50,
            'ema_long': 200,
            'adx_period': 14,
            'adx_threshold': 25,
            'rsi_bullish': 55,
            'rsi_bearish': 45,
            'atr_period': 14,
            'atr_threshold_pct': 0.001
        }
        self._cache = {}  # Cache for incremental updates

    def calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate EMA using numpy for efficiency.

        Args:
            prices: Array of prices.
            period: EMA period.

        Returns:
            Array of EMA values.
        """
        try:
            if len(prices) < period:
                logger.warning(f"Insufficient data for EMA: {len(prices)} < {period}")
                return np.full_like(prices, np.nan, dtype=float)
            ema = np.zeros_like(prices, dtype=float)
            alpha = 2 / (period + 1)
            ema[0] = prices[0]
            for i in range(1, len(prices)):
                ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
            return np.where(np.isnan(prices), np.nan, ema)
        except Exception as e:
            logger.error(f"Error calculating EMA: {str(e)}")
            return np.full_like(prices, np.nan, dtype=float)

    def calculate_rsi(self, prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Wilder's RSI using RMA, aligned with backtest documentation.

        Args:
            prices: Array of prices.
            period: RSI period.

        Returns:
            Array of RSI values.
        """
        try:
            if len(prices) < period + 1:
                logger.warning(f"Insufficient data for RSI: {len(prices)} < {period + 1}")
                return np.full_like(prices, np.nan, dtype=float)

            deltas = np.diff(prices)
            up = np.maximum(deltas, 0)
            down = np.maximum(-deltas, 0)

            # Use RMA for smoothing (from backtest documentation)
            up_rma = self._rma(up, period)
            down_rma = self._rma(down, period)

            rs = np.where(down_rma != 0, up_rma / down_rma, np.inf)
            rsi = 100 - 100 / (1 + rs)

            # Pad with NaN for initial periods
            result = np.full_like(prices, np.nan, dtype=float)
            result[period:] = rsi
            return result
        except Exception as e:
            logger.error(f"Error calculating RSI: {str(e)}")
            return np.full_like(prices, np.nan, dtype=float)

    def _rma(self, source: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate RMA (Running Moving Average) for RSI and ADX, per backtest documentation.

        Args:
            source: Input array.
            period: Smoothing period.

        Returns:
            Array of RMA values.
        """
        try:
            alpha = 1 / period
            result = np.zeros_like(source, dtype=float)
            result[0] = np.mean(source[:period]) if len(source) >= period else np.nan
            for i in range(1, len(source)):
                result[i] = alpha * source[i] + (1 - alpha) * (
                    result[i - 1] if not np.isnan(result[i - 1]) else source[i])
            return result
        except Exception as e:
            logger.error(f"Error calculating RMA: {str(e)}")
            return np.full_like(source, np.nan, dtype=float)

    def calculate_adx(self, df: Dict[str, np.ndarray], period: int = 14) -> np.ndarray:
        """
        Calculate ADX with RMA smoothing, aligned with backtest documentation.

        Args:
            df: Dictionary with 'high', 'low', 'close' arrays.
            period: ADX period.

        Returns:
            Array of ADX values.
        """
        try:
            high, low, close = df['high'], df['low'], df['close']
            if len(high) < period + 1:
                logger.warning(f"Insufficient data for ADX: {len(high)} < {period + 1}")
                return np.full_like(high, np.nan, dtype=float)

            # True Range
            tr = np.maximum.reduce([
                high[1:] - low[1:],
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            ])

            # Directional Movement
            plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                               np.maximum(high[1:] - high[:-1], 0), 0)
            minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                                np.maximum(low[:-1] - low[1:], 0), 0)

            # Smooth TR, +DM, -DM using RMA
            atr = self._rma(tr, period)
            plus_dm_rma = self._rma(plus_dm, period)
            minus_dm_rma = self._rma(minus_dm, period)

            # Calculate +DI, -DI
            plus_di = 100 * plus_dm_rma / np.where(atr != 0, atr, np.nan)
            minus_di = 100 * minus_dm_rma / np.where(atr != 0, atr, np.nan)

            # Calculate DX and ADX
            dx = 100 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) != 0, plus_di + minus_di, np.nan)
            adx = self._rma(dx, period)

            # Pad with NaN for initial periods
            result = np.full_like(high, np.nan, dtype=float)
            result[period:] = adx
            return result
        except Exception as e:
            logger.error(f"Error calculating ADX: {str(e)}")
            return np.full_like(high, np.nan, dtype=float)

    def calculate_atr(self, df: Dict[str, np.ndarray], period: int = 14) -> np.ndarray:
        """
        Calculate ATR with RMA smoothing, aligned with backtest documentation.

        Args:
            df: Dictionary with 'high', 'low', 'close' arrays.
            period: ATR period.

        Returns:
            Array of ATR values.
        """
        try:
            high, low, close = df['high'], df['low'], df['close']
            if len(high) < period + 1:
                logger.warning(f"Insufficient data for ATR: {len(high)} < {period + 1}")
                return np.full_like(high, np.nan, dtype=float)

            tr = np.maximum.reduce([
                high[1:] - low[1:],
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            ])

            atr = self._rma(tr, period)
            result = np.full_like(high, np.nan, dtype=float)
            result[period:] = atr
            return result
        except Exception as e:
            logger.error(f"Error calculating ATR: {str(e)}")
            return np.full_like(high, np.nan, dtype=float)

    def is_trending(self, timeframe: str = '15m', higher_timeframe: str = '1h') -> bool:
        """
        Determine if the market is trending, confirmed by a higher timeframe.

        Args:
            timeframe: Primary timeframe (e.g., '15m').
            higher_timeframe: Confirmation timeframe (e.g., '1h').

        Returns:
            True if trending, False otherwise.
        """
        try:
            if timeframe not in self.market_data or higher_timeframe not in self.market_data:
                logger.error(f"Invalid timeframe: {timeframe} or {higher_timeframe}")
                return False

            # Primary timeframe analysis
            df = self.market_data[timeframe]
            close = df['close'].values
            ema_short = self.calculate_ema(close, self.settings['ema_short'])
            ema_mid = self.calculate_ema(close, self.settings['ema_mid'])
            ema_long = self.calculate_ema(close, self.settings['ema_long'])

            bullish = ema_short[-1] > ema_mid[-1] > ema_long[-1]
            bearish = ema_short[-1] < ema_mid[-1] < ema_long[-1]
            if not (bullish or bearish):
                return False

            # Confirm with ADX
            df_np = {'high': df['high'].values, 'low': df['low'].values, 'close': close}
            adx = self.calculate_adx(df_np, self.settings['adx_period'])
            if adx[-1] < self.settings['adx_threshold']:
                return False

            # Higher timeframe confirmation
            df_higher = self.market_data[higher_timeframe]
            close_higher = df_higher['close'].values
            ema_short_higher = self.calculate_ema(close_higher, self.settings['ema_short'])
            ema_mid_higher = self.calculate_ema(close_higher, self.settings['ema_mid'])
            ema_long_higher = self.calculate_ema(close_higher, self.settings['ema_long'])

            bullish_higher = ema_short_higher[-1] > ema_mid_higher[-1] > ema_long_higher[-1]
            bearish_higher = ema_short_higher[-1] < ema_mid_higher[-1] < ema_long_higher[-1]
            if bullish and not bullish_higher:
                return False
            if bearish and not bearish_higher:
                return False

            return True
        except Exception as e:
            logger.error(f"Error in is_trending: {str(e)}")
            return False

    def get_trend_bias(self, timeframe: str = '1h') -> str:
        """
        Determine trend bias (bullish, bearish, neutral) based on RSI and SMA crossover.

        Args:
            timeframe: Timeframe for analysis (e.g., '1h').

        Returns:
            Trend bias: 'bullish', 'bearish', or 'neutral'.
        """
        try:
            if timeframe not in self.market_data:
                logger.error(f"Invalid timeframe: {timeframe}")
                return "neutral"

            df = self.market_data[timeframe]
            close = df['close'].values
            rsi = self.calculate_rsi(close, self.settings['rsi_period'])

            # Add SMA crossover for bias confirmation
            sma_fast = self.calculate_ema(close, 10)  # Align with backtest documentation
            sma_slow = self.calculate_ema(close, 20)
            crossover = sma_fast[-1] > sma_slow[-1] and sma_fast[-2] <= sma_slow[-2]
            crossunder = sma_fast[-1] < sma_slow[-1] and sma_fast[-2] >= sma_slow[-2]

            if rsi[-1] > self.settings['rsi_bullish'] and crossover:
                return "bullish"
            elif rsi[-1] < self.settings['rsi_bearish'] and crossunder:
                return "bearish"
            else:
                return "neutral"
        except Exception as e:
            logger.error(f"Error in get_trend_bias: {str(e)}")
            return "neutral"

    def is_sideway(self, timeframe: str = '5m') -> bool:
        """
        Check if market is in a sideways (range-bound) condition based on ATR.

        Args:
            timeframe: Timeframe for analysis (e.g., '5m').

        Returns:
            True if sideways, False otherwise.
        """
        try:
            if timeframe not in self.market_data:
                logger.error(f"Invalid timeframe: {timeframe}")
                return False

            df = self.market_data[timeframe]
            df_np = {'high': df['high'].values, 'low': df['low'].values, 'close': df['close'].values}
            atr = self.calculate_atr(df_np, self.settings['atr_period'])
            current_price = df_np['close'][-1]
            atr_pct = atr[-1] / current_price if current_price != 0 else np.nan
            return atr_pct < self.settings['atr_threshold_pct']
        except Exception as e:
            logger.error(f"Error in is_sideway: {str(e)}")
            return False

    def analyze(self, primary_timeframe: str = '15m', higher_timeframe: str = '1h') -> Dict[str, any]:
        """
        Comprehensive trend analysis combining multiple indicators and timeframes.

        Args:
            primary_timeframe: Primary timeframe for analysis (e.g., '15m').
            higher_timeframe: Higher timeframe for confirmation (e.g., '1h').

        Returns:
            Dictionary with analysis results:
                {
                    'is_trending': bool,
                    'trend_bias': str ('bullish', 'bearish', 'neutral'),
                    'is_sideway': bool,
                    'trend_strength': float (ADX value),
                    'volatility': float (ATR as % of price)
                }
        """
        try:
            trending = self.is_trending(primary_timeframe, higher_timeframe)
            bias = self.get_trend_bias(primary_timeframe)
            sideway = self.is_sideway(primary_timeframe)

            # Calculate additional metrics
            df = self.market_data[primary_timeframe]
            df_np = {'high': df['high'].values, 'low': df['low'].values, 'close': df['close'].values}
            adx = self.calculate_adx(df_np, self.settings['adx_period'])
            atr = self.calculate_atr(df_np, self.settings['atr_period'])
            current_price = df_np['close'][-1]
            volatility = atr[-1] / current_price if current_price != 0 else np.nan

            return {
                'is_trending': trending,
                'trend_bias': bias,
                'is_sideway': sideway,
                'trend_strength': adx[-1] if not np.isnan(adx[-1]) else 0,
                'volatility': volatility if not np.isnan(volatility) else 0
            }
        except Exception as e:
            logger.error(f"Error in analyze: {str(e)}")
            return {
                'is_trending': False,
                'trend_bias': 'neutral',
                'is_sideway': False,
                'trend_strength': 0,
                'volatility': 0
            }

    @lru_cache(maxsize=128)
    def _get_cached_indicators(self, symbol: str, timeframe: str, period: int, indicator: str) -> np.ndarray:
        """
        Cache indicator calculations for performance in live trading.

        Args:
            symbol: Trading pair.
            timeframe: Timeframe.
            period: Indicator period.
            indicator: 'ema', 'rsi', or 'adx'.

        Returns:
            Cached indicator array.
        """
        df = self.market_data[timeframe]
        if indicator == 'ema':
            return self.calculate_ema(df['close'].values, period)
        elif indicator == 'rsi':
            return self.calculate_rsi(df['close'].values, period)
        elif indicator == 'adx':
            return self.calculate_adx(
                {'high': df['high'].values, 'low': df['low'].values, 'close': df['close'].values},
                period
            )
        return np.full_like(df['close'].values, np.nan, dtype=float)

    def update_incremental(self, timeframe: str, new_candle: Dict) -> None:
        """
        Update market data incrementally for real-time trading.

        Args:
            timeframe: Timeframe to update.
            new_candle: Dictionary with 'open', 'high', 'low', 'close', 'volume'.
        """
        try:
            if timeframe not in self.market_data:
                logger.error(f"Invalid timeframe: {timeframe}")
                return

            df = self.market_data[timeframe]
            new_row = pd.Series(new_candle, index=['open', 'high', 'low', 'close', 'volume'])
            self.market_data[timeframe] = pd.concat([df, new_row.to_frame().T], ignore_index=True)
            self._cache.clear()  # Invalidate cache on update
        except Exception as e:
            logger.error(f"Error in update_incremental: {str(e)}")

    def for_risk_manager(self, symbol: str, timeframe: str = '15m') -> Dict:
        """
        Provide trend data for integration with RiskManager.

        Args:
            symbol: Trading pair.
            timeframe: Timeframe for analysis.

        Returns:
            Dictionary with trend data for risk assessment.
        """
        try:
            analysis = self.analyze(timeframe)
            return {
                'trend_strength': analysis['trend_strength'],  # ADX
                'volatility': analysis['volatility'],  # ATR %
                'is_trending': analysis['is_trending'],
                'trend_bias': analysis['trend_bias']
            }
        except Exception as e:
            logger.error(f"Error in for_risk_manager: {str(e)}")
            return {
                'trend_strength': 0,
                'volatility': 0,
                'is_trending': False,
                'trend_bias': 'neutral'
            }