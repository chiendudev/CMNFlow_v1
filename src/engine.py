import asyncio
import logging
from typing import Dict
from src.core.settings import Settings
from src.core.storage import Storage
from src.core.events import EventBus, TradeEvent
from src.exchange.client import ExchangeClient
from src.exchange.websocket import WebSocketClient
from src.exchange.kline_manager import KlineManager
from src.strategy.signals import SignalGenerator
from src.trading.portfolio import Portfolio

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings)
        self.event_bus = EventBus()
        self.exchange = ExchangeClient(settings)
        self.websocket = WebSocketClient(settings, self.event_bus)
        self.portfolio = Portfolio(settings)
        self.kline_managers: Dict[str, KlineManager] = {
            symbol: KlineManager(symbol, settings) for symbol in settings.symbols
        }
        self.signal_generator = SignalGenerator(settings)
        self.event_bus.subscribe("trade", self._handle_trade)
        self.event_bus.subscribe("signal", self._handle_signal)

    async def _handle_trade(self, event: TradeEvent) -> None:
        trade = Trade.model_validate(event.data)
        await self.kline_managers[event.symbol].update(trade)
        for tf in self.settings.timeframes:
            klines = self.kline_managers[event.symbol].get_klines(tf)
            if klines:
                kline = klines[-1]
                signals = self.signal_generator.generate_signals(kline, tf, [])
                for signal in signals:
                    await self.event_bus.publish("signal", SignalEvent(event.symbol, tf, signal))
        await self.portfolio.update_positions(event.symbol, trade.price)

    async def _handle_signal(self, event: SignalEvent) -> None:
        order = Order(
            symbol=event.symbol,
            side=OrderSide.BUY if event.signal["type"] == "buy" else OrderSide.SELL,
            position_side=PositionSide.BOTH,
            quantity=self.settings.trade_quantity,
            price=event.signal["entry"],
            status=OrderStatus.FILLED
        )
        await self.portfolio.process_order(order)
        self.storage.save_position(event.symbol, event.signal)

    async def start_historical(self, symbol: str, start_date: str, end_date: str) -> None:
        await self.kline_managers[symbol].fetch_historical(self.exchange, start_date, end_date)
        self.storage.save_klines(symbol, self.kline_managers[symbol].klines)

    async def start_realtime(self) -> None:
        await self.websocket.run()

    async def run(self) -> None:
        tasks = [self.start_realtime()]
        await asyncio.gather(*tasks)