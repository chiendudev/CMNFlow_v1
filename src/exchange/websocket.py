import websockets
import json
import logging
from src.core.events import EventBus, TradeEvent, OrderBookEvent, FundingRateEvent, MarkPriceEvent, LiquidationEvent, KlineEvent
from src.core.settings import Settings
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, settings: Settings, event_bus: EventBus):
        self.settings = settings
        self.event_bus = event_bus
        self.uri = settings.ws_url

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def run(self) -> None:
        try:
            async with websockets.connect(self.uri) as ws:
                streams = [f"{symbol.lower()}@aggTrade" for symbol in self.settings.symbols] + \
                          [f"{symbol.lower()}@depth@100ms" for symbol in self.settings.symbols] + \
                          [f"{symbol.lower()}@markPrice@1s" for symbol in self.settings.symbols] + \
                          [f"{symbol.lower()}@fundingRate@1s" for symbol in self.settings.symbols] + \
                          [f"{symbol.lower()}@forceOrder" for symbol in self.settings.symbols] + \
                          [f"{symbol.lower()}@kline_{tf}" for symbol in self.settings.symbols for tf in self.settings.timeframes]
                await ws.send(json.dumps({"method": "SUBSCRIBE", "params": streams, "id": 1}))
                logger.info("WebSocket connected, subscribed to: %s", streams)

                async for message in ws:
                    data = json.loads(message)
                    if "stream" in data and "data" in data:
                        symbol = next(s for s in self.settings.symbols if s.lower() in data["stream"]).upper()
                        stream_type = data["stream"].split("@")[1].split("@")[0]
                        if stream_type == "aggTrade":
                            await self.event_bus.publish("trade", TradeEvent(symbol=symbol, data=data["data"]))
                        elif stream_type == "depth":
                            await self.event_bus.publish("order_book", OrderBookEvent(
                                symbol=symbol,
                                bids=[(float(b[0]), float(b[1])) for b in data["data"]["bids"]],
                                asks=[(float(a[0]), float(a[1])) for a in data["data"]["asks"]],
                                timestamp=data["data"]["E"]
                            ))
                        elif stream_type == "markPrice":
                            await self.event_bus.publish("mark_price", MarkPriceEvent(
                                symbol=symbol,
                                mark_price=float(data["data"]["p"]),
                                timestamp=data["data"]["E"]
                            ))
                        elif stream_type == "fundingRate":
                            await self.event_bus.publish("funding_rate", FundingRateEvent(
                                symbol=symbol,
                                funding_rate=float(data["data"]["r"]),
                                funding_time=data["data"]["T"]
                            ))
                        elif stream_type == "forceOrder":
                            order = data["data"]["o"]
                            await self.event_bus.publish("liquidation", LiquidationEvent(
                                symbol=symbol,
                                side=order["S"],
                                price=float(order["p"]),
                                quantity=float(order["q"]),
                                timestamp=order["T"]
                            ))
                        elif stream_type.startswith("kline_"):
                            kline = data["data"]["k"]
                            timeframe = kline["i"]
                            await self.event_bus.publish("kline", KlineEvent(
                                symbol=symbol,
                                timeframe=timeframe,
                                open_time=kline["t"],
                                close_time=kline["T"],
                                open=float(kline["o"]),
                                high=float(kline["h"]),
                                low=float(kline["l"]),
                                close=float(kline["c"]),
                                volume=float(kline["v"]),
                                num_trades=kline["n"],
                                is_closed=kline["x"]
                            ))
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("WebSocket run failed: %s", e)
            raise