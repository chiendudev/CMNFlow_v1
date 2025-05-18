from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv
import os
import json
from trading.enums import TradeMode

load_dotenv()

def get_env_list(key: str, default: str) -> List[str]:
    return json.loads(os.getenv(key, default))

@dataclass
class Settings:
    symbols: List[str] = field(default_factory=lambda: get_env_list("SYMBOLS", '["BTCUSDT", "ETHUSDT"]'))
    timeframes: List[str] = field(default_factory=lambda: get_env_list("TIMEFRAMES", '["1m", "5m", "15m"]'))
    historical_intervals: List[str] = field(default_factory=lambda: get_env_list("HISTORICAL_INTERVALS", '["1h", "4h"]'))

    ws_url: str = os.getenv("WS_URL", "wss://fstream.binance.com/stream")
    rest_api_url: str = os.getenv("REST_API_URL", "https://fapi.binance.com")
    max_klines: int = int(os.getenv("MAX_KLINES", 1000))
    save_interval: int = int(os.getenv("SAVE_INTERVAL", 300))
    throttle_rate: float = float(os.getenv("THROTTLE_RATE", 0.1))
    price_precision: int = int(os.getenv("PRICE_PRECISION", 2))
    volume_threshold: float = float(os.getenv("VOLUME_THRESHOLD", 2.0))
    min_trades: int = int(os.getenv("MIN_TRADES", 10))
    volume_percent: float = float(os.getenv("VOLUME_PERCENT", 0.05))
    price_range_pct: float = float(os.getenv("PRICE_RANGE_PCT", 0.005))
    confluence_range_pct: float = float(os.getenv("CONFLUENCE_RANGE_PCT", 0.002))
    value_area_pct: float = float(os.getenv("VALUE_AREA_PCT", 0.7))
    min_reliability: float = float(os.getenv("MIN_RELIABILITY", 0.7))
    max_breakout_prob: float = float(os.getenv("MAX_BREAKOUT_PROB", 0.5))
    risk_reward_ratio: float = float(os.getenv("RISK_REWARD_RATIO", 2.0))
    stop_loss_buffer: float = float(os.getenv("STOP_LOSS_BUFFER", 0.005))
    stop_hunt_window: int = int(os.getenv("STOP_HUNT_WINDOW", 10))
    stop_hunt_price_move: float = float(os.getenv("STOP_HUNT_PRICE_MOVE", 0.005))
    stop_hunt_volume_spike: float = float(os.getenv("STOP_HUNT_VOLUME_SPIKE", 3.0))
    stop_hunt_taker_ratio: float = float(os.getenv("STOP_HUNT_TAKER_RATIO", 0.7))
    stop_hunt_reversal: float = float(os.getenv("STOP_HUNT_REVERSAL", 0.003))
    stop_hunt_risk_window: int = int(os.getenv("STOP_HUNT_RISK_WINDOW", 30))
    rsi_period: int = int(os.getenv("RSI_PERIOD", 14))
    atr_period: int = int(os.getenv("ATR_PERIOD", 14))
    ema_fast_period: int = int(os.getenv("EMA_FAST_PERIOD", 9))
    ema_slow_period: int = int(os.getenv("EMA_SLOW_PERIOD", 21))
    rsi_oversold: int = int(os.getenv("RSI_OVERSOLD", 30))
    rsi_overbought: int = int(os.getenv("RSI_OVERBOUGHT", 70))
    atr_stop_loss_factor: float = float(os.getenv("ATR_STOP_LOSS_FACTOR", 1.5))
    atr_take_profit_factor: float = float(os.getenv("ATR_TAKE_PROFIT_FACTOR", 3.0))
    trade_quantity: float = float(os.getenv("TRADE_QUANTITY", 0.1))
    leverage: int = int(os.getenv("LEVERAGE", 10))
    use_sl_tp: bool = os.getenv("USE_SL_TP", "True").lower() == "true"
    trade_mode: TradeMode = TradeMode[os.getenv("TRADE_MODE", "ONE_WAY")]
    api_key: str = os.getenv("API_KEY", "test_key")
    api_secret: str = os.getenv("API_SECRET", "test_secret")
