from datetime import datetime
from typing import Dict, List, Optional
import logging
from core.settings import Settings
from core.events import EventBus, KlineEvent, OrderBookEvent, FundingRateEvent, SignalEvent
from data.kline import Kline
from strategy.indicators import Indicators
from trading.portfolio import Portfolio

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self, settings: Settings, event_bus: EventBus, portfolio: Portfolio):
        self.settings = settings
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.indicators = Indicators()
        self.storage = Storage(settings, event_bus)
        self.latest_klines: Dict[str, Dict[str, Kline]] = {}  # {symbol: {timeframe: Kline}}
        self.latest_order_books: Dict[str, OrderBookSnapshot] = {}  # {symbol: OrderBookSnapshot}
        self.latest_funding_rates: Dict[str, float] = {}  # {symbol: funding_rate}
        # Đăng ký handlers
        self.event_bus.subscribe("kline", self._handle_kline, priority=1,
                                filter_func=lambda e: e.timeframe in self.settings.timeframes)
        self.event_bus.subscribe("order_book", self._handle_order_book, priority=2)
        self.event_bus.subscribe("funding_rate", self._handle_funding_rate, priority=2)

    async def _handle_kline(self, event: KlineEvent) -> None:
        """Lưu kline mới nhất và tạo tín hiệu nếu nến đóng."""
        symbol, timeframe = event.symbol, event.timeframe
        if symbol not in self.latest_klines:
            self.latest_klines[symbol] = {}
        self.latest_klines[symbol][timeframe] = Kline(
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
        if event.is_closed:
            signals = self.generate_signals(symbol, timeframe)
            for signal in signals:
                await self.event_bus.publish("signal", SignalEvent(symbol, timeframe, signal))
                logger.debug("Generated signal for %s, timeframe=%s: %s", symbol, timeframe, signal["type"])

    async def _handle_order_book(self, event: OrderBookEvent) -> None:
        """Lưu order book mới nhất."""
        self.latest_order_books[event.symbol] = OrderBookSnapshot(
            bids=event.bids,
            asks=event.asks,
            timestamp=event.timestamp
        )

    async def _handle_funding_rate(self, event: FundingRateEvent) -> None:
        """Lưu funding rate mới nhất."""
        self.latest_funding_rates[event.symbol] = event.funding_rate

    def generate_signals(self, symbol: str, timeframe: str) -> List[Dict]:
        """Tạo tín hiệu giao dịch dựa trên confluence và dữ liệu thị trường."""
        signals = []
        if symbol not in self.latest_klines or timeframe not in self.latest_klines[symbol]:
            logger.debug("No kline data for %s, timeframe=%s", symbol, timeframe)
            return signals

        kline = self.latest_klines[symbol][timeframe]
        margin_ratio = self.portfolio.get_margin_ratio()
        if margin_ratio > 80:
            logger.warning("Margin ratio too high (%.2f%%), skipping signals for %s", margin_ratio, symbol)
            return signals

        # Lấy dữ liệu
        klines = self._get_historical_klines(symbol, timeframe, self.settings.max_klines)
        funding_rate = self.latest_funding_rates.get(symbol, 0.0)
        order_book = self.latest_order_books.get(symbol)

        # Tính chỉ báo
        closes = [k.close for k in klines]
        rsi = self.indicators.rsi(closes, self.settings.rsi_period)
        ema_fast = self.indicators.ema(closes, self.settings.ema_fast_period)
        ema_slow = self.indicators.ema(closes, self.settings.ema_slow_period)
        atr = self.indicators.atr([k.high for k in klines], [k.low for k in klines],
                                 [k.close for k in klines], self.settings.atr_period)
        volume_avg = sum(k.volume for k in klines[-20:]) / 20 if len(klines) >= 20 else kline.volume

        # Tìm mức hỗ trợ/kháng cự
        support, resistance = self.indicators.find_support_resistance(klines, window=20)

        # Logic confluence
        buy_conditions = [
            rsi < self.settings.rsi_oversold,  # RSI quá bán
            kline.close > ema_fast > ema_slow,  # EMA crossover
            kline.volume > volume_avg * 1.5,  # Volume tăng đột biến
            funding_rate < self.settings.funding_rate_threshold  # Funding rate âm
        ]
        sell_conditions = [
            rsi > self.settings.rsi_overbought,  # RSI quá mua
            kline.close < ema_fast < ema_slow,  # EMA crossover
            kline.volume > volume_avg * 1.5,  # Volume tăng đột biến
            funding_rate > -self.settings.funding_rate_threshold  # Funding rate dương
        ]

        # Tính SL/TP
        entry_price = kline.close
        sl_distance = atr * self.settings.sl_atr_multiplier
        tp_distance = atr * self.settings.tp_atr_multiplier
        buy_sl = max(entry_price - sl_distance, support or 0) if support else entry_price - sl_distance
        buy_tp = min(entry_price + tp_distance, resistance or float("inf")) if resistance else entry_price + tp_distance
        sell_sl = min(entry_price + sl_distance, resistance or float("inf")) if resistance else entry_price + sl_distance
        sell_tp = max(entry_price - tp_distance, support or 0) if support else entry_price - tp_distance

        # Tạo tín hiệu nếu đủ điều kiện confluence
        if sum(buy_conditions) >= self.settings.min_confluence_count:
            signals.append({
                "type": "buy",
                "entry": entry_price,
                "stop_loss": buy_sl,
                "take_profit": buy_tp,
                "timeframe": timeframe
            })
        if sum(sell_conditions) >= self.settings.min_confluence_count:
            signals.append({
                "type": "sell",
                "entry": entry_price,
                "stop_loss": sell_sl,
                "take_profit": sell_tp,
                "timeframe": timeframe
            })

        return signals

    def _get_historical_klines(self, symbol: str, timeframe: str, limit: int) -> List[Kline]:
        """Lấy dữ liệu kline lịch sử từ Storage."""
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - limit * 60 * 1000  # Giả sử timeframe là phút
        return self.storage.get_klines(symbol, timeframe, start_time, end_time)[:limit]