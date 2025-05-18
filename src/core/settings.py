from pydantic_settings import BaseSettings
from typing import List
from src.trading.enums import KlineIntervals

class Settings(BaseSettings):
    symbols: List[str] = ["BTCUSDT"]
    api_key: str
    api_secret: str
    timeframes: List[str] = ["5m", "15m"]
    base_timeframe: str = "5m"
    rsi_period: int = 14
    ema_fast_period: int = 12
    ema_slow_period: int = 26
    atr_period: int = 14
    max_klines: int = 1000
    throttle_rate: float = 0.1
    price_precision: int = 2
    trade_quantity: float = 0.001
    confluence_range_pct: float = 0.01
    ws_url: str = "wss://fstream.binance.com/ws"
    max_risk_per_trade: float = 0.01
    trailing_stop_distance: float = 100.0
    leverage: float = 10.0
    hedging_mode: bool = True
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    min_confluence_count: int = 3
    sl_atr_multiplier: float = 2.0
    tp_atr_multiplier: float = 4.0
    funding_rate_threshold: float = -0.0001
    maker_fee: float = 0.0002
    taker_fee: float = 0.0004
    oco_enabled: bool = True
    db_path: str = "data/trading.db"
    data_retention_days: int = 30
    cache_size: int = 1000
    max_margin_ratio: float = 0.80
    correlation_threshold: float = 0.80
    volatility_threshold: float = 0.02
    enabled_events: List[str] = [
        "kline", "order_book", "order_book_snapshot", "funding_rate", "mark_price", "signal",
        "order", "risk", "trade", "liquidation", "position"
    ]
    log_level: str = "INFO"
    log_directory: str = "logs"
    log_rotation_size: int = 10 * 1024 * 1024  # 10MB

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"