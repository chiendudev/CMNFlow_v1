import logging
import sqlite3
from typing import List, Any, Dict
from datetime import datetime

from src.core.settings import Settings
from src.core.events import EventBus, KlineEvent, FundingRateEvent
from src.core.logging_config import get_logger, set_log_context
from src.data.kline import Kline

logger = get_logger(__name__)

class Storage:
    def __init__(self, settings: Settings, event_bus: EventBus):
        self.settings = settings
        self.event_bus = event_bus
        self.db_path = settings.db_path
        self._create_tables()
        logger.info("Initialized SQLite database at %s", self.db_path)

    def _create_tables(self):
        """Tạo các bảng SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS klines (
                        symbol TEXT,
                        timeframe TEXT,
                        open_time INTEGER,
                        close_time INTEGER,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL,
                        num_trades INTEGER,
                        PRIMARY KEY (symbol, timeframe, open_time)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS funding_rates (
                        symbol TEXT,
                        timestamp INTEGER,
                        rate REAL,
                        PRIMARY KEY (symbol, timestamp)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id TEXT,
                        symbol TEXT,
                        side TEXT,
                        position_side TEXT,
                        type TEXT,
                        quantity REAL,
                        price REAL,
                        status TEXT,
                        timestamp INTEGER,
                        PRIMARY KEY (order_id)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        symbol TEXT,
                        side TEXT,
                        quantity REAL,
                        entry_price REAL,
                        stop_loss REAL,
                        trailing_stop REAL,
                        timestamp INTEGER,
                        PRIMARY KEY (symbol, side)
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logger.error("Failed to create tables: %s", e)
            raise

    async def initialize(self):
        """Khởi tạo Storage và đăng ký sự kiện."""
        set_log_context()
        await self._subscribe_events()
        logger.info("Storage initialized")

    async def _subscribe_events(self):
        """Đăng ký sự kiện kline và funding_rate."""
        await self.event_bus.subscribe("kline", self.save_kline, priority=1)
        await self.event_bus.subscribe("funding_rate", self.save_funding_rate, priority=1)

    async def save_kline(self, event: KlineEvent):
        """Lưu kline vào database."""
        set_log_context(symbol=event.symbol, timeframe=event.timeframe)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO klines (
                        symbol, timeframe, open_time, close_time, open, high, low, close, volume, num_trades
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.symbol, event.timeframe, event.open_time, event.close_time,
                    event.open, event.high, event.low, event.close, event.volume, event.num_trades
                ))
                conn.commit()
                logger.debug("Saved kline: symbol=%s, timeframe=%s, open_time=%d",
                             event.symbol, event.timeframe, event.open_time)
        except sqlite3.Error as e:
            logger.error("Failed to save kline for %s: %s", event.symbol, e)

    async def save_funding_rate(self, event: FundingRateEvent):
        """Lưu funding rate vào database."""
        set_log_context(symbol=event.symbol)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO funding_rates (symbol, timestamp, rate)
                    VALUES (?, ?, ?)
                """, (event.symbol, event.timestamp, event.funding_rate))
                conn.commit()
                logger.debug("Saved funding rate: symbol=%s, rate=%.6f", event.symbol, event.funding_rate)
        except sqlite3.Error as e:
            logger.error("Failed to save funding rate for %s: %s", event.symbol, e)

    def get_klines(self, symbol: str, timeframe: str, limit: int = 100) -> List[Kline]:
        """Lấy kline từ database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume, num_trades
                    FROM klines
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY open_time DESC
                    LIMIT ?
                """, (symbol, timeframe, limit))
                rows = cursor.fetchall()
                return [Kline(
                    symbol=row[0], timeframe=row[1], open_time=row[2], close_time=row[3],
                    open=row[4], high=row[5], low=row[6], close=row[7], volume=row[8], num_trades=row[9]
                ) for row in rows[::-1]]  # Đảo ngược để theo thứ tự thời gian tăng dần
        except sqlite3.Error as e:
            logger.error("Failed to get klines for %s: %s", symbol, e)
            return []

    def get_funding_rates(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Lấy funding rates từ database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT timestamp, rate
                    FROM funding_rates
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (symbol, limit))
                rows = cursor.fetchall()
                return [{"timestamp": row[0], "funding_rate": row[1]} for row in rows]
        except sqlite3.Error as e:
            logger.error("Failed to get funding rates for %s: %s", symbol, e)
            return []

    async def save_order(self, order: Dict[str, Any]):
        """Lưu order vào database."""
        set_log_context(symbol=order["symbol"])
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, symbol, side, position_side, type, quantity, price, status, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order["order_id"], order["symbol"], order["side"], order["position_side"],
                    order["type"], order["quantity"], order["price"], order["status"],
                    order.get("timestamp", int(datetime.now().timestamp() * 1000))
                ))
                conn.commit()
                logger.debug("Saved order: symbol=%s, order_id=%s", order["symbol"], order["order_id"])
        except sqlite3.Error as e:
            logger.error("Failed to save order for %s: %s", order["symbol"], e)

    async def save_position_async(self, position: Any):
        """Lưu position vào database (bất đồng bộ)."""
        set_log_context(symbol=position.symbol)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO positions (
                        symbol, side, quantity, entry_price, stop_loss, trailing_stop, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    position.symbol, position.side, position.quantity, position.entry_price,
                    position.stop_loss, position.trailing_stop,
                    int(datetime.now().timestamp() * 1000)
                ))
                conn.commit()
                logger.debug("Saved position: symbol=%s, side=%s", position.symbol, position.side)
        except sqlite3.Error as e:
            logger.error("Failed to save position for %s: %s", position.symbol, e)