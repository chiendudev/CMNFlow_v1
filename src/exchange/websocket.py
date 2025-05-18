import websockets
import json
import logging
from src.core.events import EventBus, TradeEvent
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
        """Run WebSocket client to receive real-time trades."""
        try:
            async with websockets.connect(self.uri) as ws:
                streams = [f"{symbol.lower()}@aggTrade" for symbol in self.settings.symbols]
                await ws.send(json.dumps({"method": "SUBSCRIBE", "params": streams, "id": 1}))
                logger.info("WebSocket connected, subscribed to: %s", streams)

                async for message in ws:
                    data = json.loads(message)
                    if "stream" in data and "data" in data:
                        symbol = next(s for s in self.settings.symbols if s.lower() in data["stream"]).upper()
                        await self.event_bus.publish("trade", TradeEvent(symbol=symbol, data=data["data"]))
                    elif "result" in data and data.get("id") == 1:
                        logger.debug("Subscription confirmed: %s", data)
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("WebSocket run failed: %s", e)
            raise