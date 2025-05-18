import sqlite3
import custom_logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential
from core.settings import Settings
from core.events import EventBus, KlineEvent, OrderBookEvent, FundingRateEvent, OrderEvent
from data.kline import Kline, OrderBookSnapshot
from data.trade import Trade
from trading.orders import Order, OCOOrder
from trading.enums import OrderSide, PositionSide, OrderType, OrderStatus, TimeInForce
from trading.portfolio import Position

logger = logging.getLogger(__name__)

class Storage:
    def __init__(self, settings: Settings, event_bus: Optional[EventBus] = None):
        self.settings = settings
        self.db_path = settings.db_path
        self.event_bus = event_bus
        self.cache: Dict[str, Dict] = {}  # In-memory cache
        self._init_db()
        if event_bus:
            self._subscribe_events()

    def _init_db(self) -> None:
        """Khởi tạo SQLite database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Bảng klines
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
                # Bảng trades
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        symbol TEXT,
                        trade_id TEXT,
                        price REAL,
                        quantity REAL,
                        timestamp INTEGER,
                        is_buyer_maker INTEGER,
                        PRIMARY KEY (symbol, trade_id)
                    )
                """)
                # Bảng order_book
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS order_book (
                        symbol TEXT,
                        timestamp INTEGER,
                        bids TEXT,
                        asks TEXT,
                        PRIMARY KEY (symbol, timestamp)
                    )
                """)
                # Bảng funding_rate
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS funding_rate (
                        symbol TEXT,
                        timestamp INTEGER,
                        rate REAL,
                        PRIMARY KEY (symbol, timestamp)
                    )
                """)
                # Bảng positions
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        symbol TEXT,
                        side TEXT,
                        quantity REAL,
                        entry_price REAL,
                        current_price REAL,
                        stop_loss REAL,
                        take_profit REAL,
                        trailing_stop REAL,
                        unrealized_pnl REAL,
                        leverage REAL,
                        liquidation_price REAL,
                        initial_margin REAL,
                        maintenance_margin REAL,
                        PRIMARY KEY (symbol, side)
                    )
                """)
                # Bảng orders
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id TEXT,
                        symbol TEXT,
                        side TEXT,
                        position_side TEXT,
                        type TEXT,
                        quantity REAL,
                        price REAL,
                        stop_price REAL,
                        reduce_only INTEGER,
                        close_position INTEGER,
                        time_in_force TEXT,
                        status TEXT,
                        client_order_id TEXT,
                        fee REAL,
                        executed_qty REAL,
                        avg_price REAL,
                        is_oco INTEGER,
                        oco_list_id TEXT,
                        PRIMARY KEY (order_id)
                    )
                """)
                conn.commit()
                logger.info("Initialized SQLite database at %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def _subscribe_events(self) -> None:
        """Đăng ký nhận sự kiện từ EventBus."""
        self.event_bus.subscribe("kline", self._handle_kline, priority=2)
        self.event_bus.subscribe("order_book", self._handle_order_book, priority=2)
        self.event_bus.subscribe("funding_rate", self._handle_funding_rate, priority=2)
        self.event_bus.subscribe("order", self._handle_order, priority=3)
        logger.debug("Subscribed to EventBus events for Storage")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _handle_kline(self, event: KlineEvent) -> None:
        """Lưu kline từ sự kiện."""
        kline = Kline(
            symbol=event.symbol,
            timeframe=event.timeframe,
            open_time=event.open_time,
            close_time=event.close_time,
            open=event.open,
            high=event.high,
            low=event.low,
            close=event.close,
            volume=event.volume,
            num_trades=event.num_trades,
            is_closed=event.is_closed
        )
        self.save_klines(event.symbol, [kline])
        logger.debug("Saved kline for %s, timeframe=%s, open_time=%s", event.symbol, event.timeframe, event.open_time)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _handle_order_book(self, event: OrderBookEvent) -> None:
        """Lưu order book từ sự kiện."""
        order_book = OrderBookSnapshot(
            bids=event.bids,
            asks=event.asks,
            timestamp=event.timestamp
        )
        self.save_order_book(event.symbol, order_book)
        logger.debug("Saved order book for %s, timestamp=%s", event.symbol, event.timestamp)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _handle_funding_rate(self, event: FundingRateEvent) -> None:
        """Lưu funding rate từ sự kiện."""
        self.save_funding_rate(event.symbol, event.funding_rate, event.timestamp)
        logger.debug("Saved funding rate for %s, timestamp=%s", event.symbol, event.timestamp)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _handle_order(self, event: OrderEvent) -> None:
        """Lưu order hoặc OCO order từ sự kiện."""
        if isinstance(event.order, OCOOrder):
            self.save_oco_order(event.order)
            logger.debug("Saved OCO order for %s, list_id=%s", event.symbol, event.order.order_list_id)
        else:
            self.save_order(event.order)
            logger.debug("Saved order for %s, order_id=%s", event.symbol, event.order.order_id)

    @lru_cache(maxsize=1000)
    def get_klines(self, symbol: str, timeframe: str, start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[Kline]:
        """Lấy kline từ database hoặc cache."""
        cache_key = f"kline_{symbol}_{timeframe}_{start_time}_{end_time}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM klines WHERE symbol = ? AND timeframe = ?"
                params = [symbol, timeframe]
                if start_time:
                    query += " AND open_time >= ?"
                    params.append(start_time)
                if end_time:
                    query += " AND open_time <= ?"
                    params.append(end_time)
                query += " ORDER BY open_time"
                cursor.execute(query, params)
                rows = cursor.fetchall()
                klines = [
                    Kline(
                        symbol=row[0],
                        timeframe=row[1],
                        open_time=row[2],
                        close_time=row[3],
                        open=row[4],
                        high=row[5],
                        low=row[6],
                        close=row[7],
                        volume=row[8],
                        num_trades=row[9]
                    ) for row in rows
                ]
                self.cache[cache_key] = klines
                return klines
        except sqlite3.Error as e:
            logger.error("Failed to get klines: %s", e)
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_klines(self, symbol: str, klines: List[Kline]) -> None:
        """Lưu kline vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for kline in klines:
                    cursor.execute("""
                        INSERT OR REPLACE INTO klines (
                            symbol, timeframe, open_time, close_time, open, high, low, close, volume, num_trades
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        kline.symbol, kline.timeframe, kline.open_time, kline.close_time,
                        kline.open, kline.high, kline.low, kline.close, kline.volume, kline.num_trades
                    ))
                conn.commit()
                self._clear_cache(f"kline_{symbol}")
                logger.debug("Saved %d klines for %s", len(klines), symbol)
        except sqlite3.Error as e:
            logger.error("Failed to save klines: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_trades(self, symbol: str, trades: List[Trade]) -> None:
        """Lưu trades vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for trade in trades:
                    cursor.execute("""
                        INSERT OR REPLACE INTO trades (
                            symbol, trade_id, price, quantity, timestamp, is_buyer_maker
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        symbol, trade.id, trade.price, trade.quantity, trade.timestamp, trade.is_buyer_maker
                    ))
                conn.commit()
                self._clear_cache(f"trade_{symbol}")
                logger.debug("Saved %d trades for %s", len(trades), symbol)
        except sqlite3.Error as e:
            logger.error("Failed to save trades: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_order_book(self, symbol: str, order_book: OrderBookSnapshot) -> None:
        """Lưu order book vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO order_book (
                        symbol, timestamp, bids, asks
                    ) VALUES (?, ?, ?, ?)
                """, (
                    symbol, order_book.timestamp,
                    json.dumps(order_book.bids),
                    json.dumps(order_book.asks)
                ))
                conn.commit()
                self._clear_cache(f"order_book_{symbol}")
                logger.debug("Saved order book for %s, timestamp=%s", symbol, order_book.timestamp)
        except sqlite3.Error as e:
            logger.error("Failed to save order book: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_funding_rate(self, symbol: str, rate: float, timestamp: int) -> None:
        """Lưu funding rate vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO funding_rate (
                        symbol, timestamp, rate
                    ) VALUES (?, ?, ?)
                """, (symbol, timestamp, rate))
                conn.commit()
                self._clear_cache(f"funding_rate_{symbol}")
                logger.debug("Saved funding rate for %s, timestamp=%s", symbol, timestamp)
        except sqlite3.Error as e:
            logger.error("Failed to save funding rate: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_position(self, position: Position) -> None:
        """Lưu position vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO positions (
                        symbol, side, quantity, entry_price, current_price, stop_loss, take_profit,
                        trailing_stop, unrealized_pnl, leverage, liquidation_price, initial_margin, maintenance_margin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position.symbol, position.side, position.quantity, position.entry_price, position.current_price,
                    position.stop_loss, position.take_profit, position.trailing_stop, position.unrealized_pnl,
                    position.leverage, position.liquidation_price, position.initial_margin, position.maintenance_margin
                ))
                conn.commit()
                self._clear_cache(f"position_{position.symbol}")
                logger.debug("Saved position for %s, side=%s", position.symbol, position.side)
        except sqlite3.Error as e:
            logger.error("Failed to save position: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_order(self, order: Order) -> None:
        """Lưu order vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, symbol, side, position_side, type, quantity, price, stop_price,
                        reduce_only, close_position, time_in_force, status, client_order_id, fee,
                        executed_qty, avg_price, is_oco, oco_list_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.order_id, order.symbol, order.side.value, order.position_side.value, order.type.value,
                    order.quantity, order.price, order.stop_price, int(order.reduce_only), int(order.close_position),
                    order.time_in_force.value, order.status.value, order.client_order_id, order.fee,
                    order.executed_qty, order.avg_price, 0, None
                ))
                conn.commit()
                self._clear_cache(f"order_{order.symbol}")
                logger.debug("Saved order for %s, order_id=%s", order.symbol, order.order_id)
        except sqlite3.Error as e:
            logger.error("Failed to save order: %s", e)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    def save_oco_order(self, oco_order: OCOOrder) -> None:
        """Lưu OCO order vào database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Lưu LIMIT order
                cursor.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, symbol, side, position_side, type, quantity, price, stop_price,
                        reduce_only, close_position, time_in_force, status, client_order_id, fee,
                        executed_qty, avg_price, is_oco, oco_list_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    oco_order.limit_client_order_id or f"oco_limit_{oco_order.list_client_order_id}",
                    oco_order.symbol, oco_order.side.value, oco_order.position_side.value, OrderType.LIMIT.value,
                    oco_order.quantity, oco_order.price, None, int(oco_order.reduce_only), 0,
                    TimeInForce.GTC.value, oco_order.status.value, oco_order.limit_client_order_id, 0.0,
                    0.0, 0.0, 1, oco_order.order_list_id
                ))
                # Lưu STOP_MARKET order
                cursor.execute("""
                    INSERT OR REPLACE INTO orders (
                        order_id, symbol, side, position_side, type, quantity, price, stop_price,
                        reduce_only, close_position, time_in_force, status, client_order_id, fee,
                        executed_qty, avg_price, is_oco, oco_list_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    oco_order.stop_client_order_id or f"oco_stop_{oco_order.list_client_order_id}",
                    oco_order.symbol, oco_order.side.value, oco_order.position_side.value, OrderType.STOP_MARKET.value,
                    oco_order.quantity, oco_order.stop_limit_price, oco_order.stop_price, int(oco_order.reduce_only), 0,
                    oco_order.stop_limit_time_in_force.value, oco_order.status.value, oco_order.stop_client_order_id, 0.0,
                    0.0, 0.0, 1, oco_order.order_list_id
                ))
                conn.commit()
                self._clear_cache(f"order_{oco_order.symbol}")
                logger.debug("Saved OCO order for %s, list_id=%s", oco_order.symbol, oco_order.order_list_id)
        except sqlite3.Error as e:
            logger.error("Failed to save OCO order: %s", e)
            raise

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Lấy positions từ database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM positions"
                params = []
                if symbol:
                    query += " WHERE symbol = ?"
                    params.append(symbol)
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [
                    Position(
                        symbol=row[0],
                        side=row[1],
                        quantity=row[2],
                        entry_price=row[3],
                        current_price=row[4],
                        stop_loss=row[5],
                        take_profit=row[6],
                        trailing_stop=row[7],
                        unrealized_pnl=row[8],
                        leverage=row[9],
                        liquidation_price=row[10],
                        initial_margin=row[11],
                        maintenance_margin=row[12],
                        orders=[]
                    ) for row in rows
                ]
        except sqlite3.Error as e:
            logger.error("Failed to get positions: %s", e)
            return []

    def get_orders(self, symbol: Optional[str] = None, is_oco: Optional[bool] = None) -> List[Order]:
        """Lấy orders từ database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM orders"
                params = []
                conditions = []
                if symbol:
                    conditions.append("symbol = ?")
                    params.append(symbol)
                if is_oco is not None:
                    conditions.append("is_oco = ?")
                    params.append(int(is_oco))
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [
                    Order(
                        order_id=row[0],
                        symbol=row[1],
                        side=OrderSide(row[2]),
                        position_side=PositionSide(row[3]),
                        type=OrderType(row[4]),
                        quantity=row[5],
                        price=row[6],
                        stop_price=row[7],
                        reduce_only=bool(row[8]),
                        close_position=bool(row[9]),
                        time_in_force=TimeInForce(row[10]),
                        status=OrderStatus(row[11]),
                        client_order_id=row[12],
                        fee=row[13],
                        executed_qty=row[14],
                        avg_price=row[15]
                    ) for row in rows
                ]
        except sqlite3.Error as e:
            logger.error("Failed to get orders: %s", e)
            return []

    def cleanup_old_data(self) -> None:
        """Xóa dữ liệu cũ dựa trên retention period."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cutoff_time = int((datetime.now() - timedelta(days=self.settings.data_retention_days)).timestamp() * 1000)
                tables = ["klines", "trades", "order_book", "funding_rate"]
                for table in tables:
                    cursor.execute(f"DELETE FROM {table} WHERE timestamp < ? OR open_time < ?", (cutoff_time, cutoff_time))
                conn.commit()
                logger.info("Cleaned up old data before %s", cutoff_time)
        except sqlite3.Error as e:
            logger.error("Failed to clean up old data: %s", e)

    def _clear_cache(self, prefix: str) -> None:
        """Xóa cache liên quan đến prefix."""
        keys_to_delete = [k for k in self.cache.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            del self.cache[key]
        logger.debug("Cleared cache for prefix: %s", prefix)