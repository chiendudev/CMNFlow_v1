from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    max_spread: float = 0.001
    symbols: List[str] = ['BTCUSDT']
    api_key: str = "a49a6fa8cf4a82c38606625cf56bbfae4cfdd94fd45cc0b24cb30b409096257f"
    api_secret: str = "eadf55a688758a5cf382217d070e632ec12bb6bffef48653446a71521cc442b9"
    timeframes: List[str] = ['5m', '15m', '1h', '4h']  # Bao gồm 4h cho Hedging
    base_timeframe: str = '5m'
    rsi_period: int = 14
    ema_fast_period: int = 12
    ema_slow_period: int = 26
    atr_period: int = 14
    max_klines: int = 1000
    throttle_rate: float = 0.1
    price_precision: int = 2
    trade_quantity: float = 0.001
    confluence_range_pct: float = 0.01
    ws_url: str = 'wss://fstream.binancefuture.com'
    rest_api_url: str = 'https://testnet.binancefuture.com'
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
    enabled_events: List[str] = ['kline', 'funding_rate', 'signal', 'order']
    log_level: str = "DEBUG"
    log_directory: str = "logs"
    log_rotation_size: int = 10485760
    grid_spacing: int = 100  # Cố định, nhưng sẽ dùng ATR động
    profit_threshold: float = 0.25  # Ngưỡng lợi nhuận Trailing One Side
    atr_multiplier: float = 1.5  # Hệ số ATR cho lưới
    bb_period: int = 20  # Kỳ Bollinger Bands
    bb_std: float = 2.0  # Độ lệch Bollinger Bands
    backtest_mode: bool = False  # Bật/tắt backtest
    backtest_kline_file: str = 'data/klines.json'  # Đường dẫn file kline
    backtest_trade_file: str = 'data/aggtrades.json'  # Đường dẫn file aggTrade

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


