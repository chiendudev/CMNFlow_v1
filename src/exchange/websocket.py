import websockets
import json
import logging
from datetime import datetime
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.events import EventBus, TradeEvent, FundingRateEvent, MarkPriceEvent, LiquidationEvent, KlineEvent
from src.core.settings import Settings

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, settings: Settings, event_bus: EventBus):
        self.settings = settings
        self.event_bus = event_bus
        self.uri = settings.ws_url

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=10))
    async def run(self) -> None:
        """Chạy WebSocket client với cơ chế retry."""
        try:
            async with websockets.connect(self.uri, ping_interval=20, ping_timeout=10) as ws:
                streams = (
                    [f"{symbol.lower()}@aggTrade" for symbol in self.settings.symbols] +
                    [f"{symbol.lower()}@markPrice@1s" for symbol in self.settings.symbols] +
                    [f"{symbol.lower()}@fundingRate@1s" for symbol in self.settings.symbols] +
                    [f"{symbol.lower()}@forceOrder" for symbol in self.settings.symbols] +
                    [f"{symbol.lower()}@kline_{tf}" for symbol in self.settings.symbols for tf in self.settings.timeframes]
                )
                await ws.send(json.dumps({"method": "SUBSCRIBE", "params": streams, "id": 1}))
                logger.info("WebSocket connected, subscribed to: %s", streams)

                async for message in ws:
                    try:
                        data = json.loads(message)
                        await self.handle_message(data)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON message: {message}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed, retrying...")
            raise
        except Exception as e:
            logger.error(f"WebSocket run failed: {e}", exc_info=True)
            raise

    async def handle_message(self, data: Dict[str, Any]) -> None:
        """Xử lý tin nhắn WebSocket và xuất bản sự kiện."""
        if "stream" not in data or "data" not in data:
            logger.debug(f"Ignoring message without stream/data: {data}")
            return

        stream = data["stream"]
        stream_parts = stream.split("@")
        if len(stream_parts) < 2:
            logger.error(f"Invalid stream format: {stream}")
            return

        # Xác định symbol chính xác
        symbol_lower = stream_parts[0]
        symbol = next((s for s in self.settings.symbols if s.lower() == symbol_lower), None)
        if not symbol:
            logger.error(f"Unknown symbol in stream: {stream}")
            return

        stream_type = stream_parts[1].split("_")[0]
        event_data = data["data"]

        if stream_type == "aggTrade":
            await self.event_bus.publish("trade", TradeEvent(
                type="trade",
                symbol=symbol,
                timestamp=event_data.get("E", int(datetime.now().timestamp() * 1000)),
                data=event_data
            ))
            logger.debug(f"Published trade event: symbol={symbol}")

        elif stream_type == "markPrice":
            await self.event_bus.publish("mark_price", MarkPriceEvent(
                type="mark_price",
                symbol=symbol,
                mark_price=float(event_data["p"]),
                timestamp=event_data["E"]
            ))
            logger.debug(f"Published mark_price event: symbol={symbol}")

        elif stream_type == "fundingRate":
            await self.event_bus.publish("funding_rate", FundingRateEvent(
                type="funding_rate",
                symbol=symbol,
                funding_rate=float(event_data["r"]),
                funding_time=event_data["T"]
            ))
            logger.debug(f"Published funding_rate event: symbol={symbol}")

        elif stream_type == "forceOrder":
            order = event_data["o"]
            await self.event_bus.publish("liquidation", LiquidationEvent(
                type="liquidation",
                symbol=symbol,
                side=order["S"],
                price=float(order["p"]),
                quantity=float(order["q"]),
                timestamp=order["T"]
            ))
            logger.debug(f"Published liquidation event: symbol={symbol}")

        elif stream_type == "kline":
            kline = event_data["k"]
            timeframe = kline["i"]
            await self.event_bus.publish("kline", KlineEvent(
                type="kline",
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
                is_closed=kline["x"],
                timestamp=event_data.get("E", int(datetime.now().timestamp() * 1000))
            ))
            logger.debug(f"Published kline event: symbol={symbol}, timeframe={timeframe}")