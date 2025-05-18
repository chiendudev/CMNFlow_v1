import asyncio
import logging
from typing import Dict
from src.core.settings import Settings
from src.core.storage import Storage
from src.data.kline import Kline
from src.data.trade import Trade
from src.core.events import EventBus, TradeEvent, OrderBookEvent, FundingRateEvent, MarkPriceEvent, SignalEvent, LiquidationEvent, KlineEvent
from src.exchange.client import ExchangeClient
from src.exchange.websocket import WebSocketClient
from src.exchange.kline_manager import KlineManager
from src.strategy.signals import SignalGenerator
from src.trading.portfolio import Portfolio
from src.trading.orders import Order
from trading.enums import OrderSide, PositionSide, OrderStatus

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings)
        self.event_bus = EventBus(settings=settings)
        self.exchange = ExchangeClient(settings)
        self.websocket = WebSocketClient(settings, self.event_bus)
        self.portfolio = Portfolio(settings, self.event_bus, self.exchange)
        self.kline_managers: Dict[str, KlineManager] = {
            symbol: KlineManager(symbol, settings) for symbol in settings.symbols
        }
        self.signal_generator = SignalGenerator(settings, self.event_bus, self.portfolio)
        self.event_bus.subscribe("trade", self._handle_trade, priority=1)
        self.event_bus.subscribe("order_book", self._handle_order_book, priority=2)
        self.event_bus.subscribe("mark_price", self._handle_mark_price, priority=2)
        self.event_bus.subscribe("funding_rate", self._handle_funding_rate, priority=2)
        self.event_bus.subscribe("liquidation", self._handle_liquidation, priority=3)
        self.event_bus.subscribe("kline", self._handle_kline, priority=1,
                                filter_func=lambda e: e.timeframe == self.settings.base_timeframe)
        self.event_bus.subscribe("signal", self._handle_signal, priority=5,
                                filter_func=lambda e: e.symbol in self.settings.symbols)

    async def _handle_trade(self, event: TradeEvent) -> None:
        trade = Trade.model_validate(event.data)
        await self.kline_managers[event.symbol].update(trade)
        for tf in self.settings.timeframes:
            klines = self.kline_managers[event.symbol].get_klines(tf)
            if klines:
                kline = klines[-1]
                signals = self.signal_generator.generate_signals(event.symbol, tf)
                for signal in signals:
                    await self.event_bus.publish("signal", SignalEvent(event.symbol, tf, signal))

    async def _handle_order_book(self, event: OrderBookEvent) -> None:
        klines = self.kline_managers[event.symbol].get_klines(self.settings.base_timeframe)
        if klines:
            klines[-1].update_order_book(event.bids, event.asks, event.timestamp)

    async def _handle_mark_price(self, event: MarkPriceEvent) -> None:
        klines = self.kline_managers[event.symbol].get_klines(self.settings.base_timeframe)
        if klines:
            klines[-1].mark_price = event.mark_price

    async def _handle_funding_rate(self, event: FundingRateEvent) -> None:
        klines = self.kline_managers[event.symbol].get_klines(self.settings.base_timeframe)
        if klines:
            klines[-1].funding_rate = event.funding_rate

    async def _handle_liquidation(self, event: LiquidationEvent) -> None:
        logger.info("Liquidation detected for %s: side=%s, price=%.2f, quantity=%.4f",
                    event.symbol, event.side, event.price, event.quantity)

    async def _handle_kline(self, event: KlineEvent) -> None:
        klines = self.kline_managers[event.symbol].get_klines(event.timeframe)
        if klines and klines[-1].open_time == event.open_time:
            klines[-1].update(event.close, event.volume, event.num_trades)
            klines[-1].is_closed = event.is_closed
        else:
            new_kline = Kline(
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
            klines.append(new_kline)

    async def _handle_signal(self, event: SignalEvent) -> None:
        logger.debug("Received signal for %s: %s", event.symbol, event.signal["type"])

    async def start_historical(self, symbol: str, start_date: str, end_date: str) -> None:
        await self.kline_managers[symbol].fetch_historical(self.exchange, start_date, end_date)
        self.storage.save_klines(symbol, self.kline_managers[symbol].klines)

    async def start_realtime(self) -> None:
        await self.portfolio.initialize()
        await self.websocket.run()

    async def run(self) -> None:
        tasks = [self.start_realtime()]
        await asyncio.gather(*tasks)