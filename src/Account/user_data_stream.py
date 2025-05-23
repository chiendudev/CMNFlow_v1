import asyncio
import json
import aiohttp
from typing import Dict, Any, Optional
import websockets
from src.core.settings import Settings
from src.core.event_dispatcher import EventDispatcher
from src.account.account_info import AccountInfo

class UserDataStream:
    """Quản lý stream dữ liệu người dùng qua WebSocket và REST API."""
    def __init__(self, settings: Settings, account_info: AccountInfo):
        self.settings = settings
        self.account_info = account_info
        self.base_url = "https://fapi.binance.com"
        self.ws_base_url = "wss://fstream.binance.com"
        self.listen_key: Optional[str] = None
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.dispatcher = EventDispatcher()

    async def start_user_data_stream(self) -> str:
        """Bắt đầu stream dữ liệu người dùng qua REST API."""
        if self.settings.backtest_mode:
            return "mock_listen_key"
        async with aiohttp.ClientSession() as session:
            headers = {"X-MBX-APIKEY": self.settings.api_key}
            async with session.post(f"{self.base_url}/fapi/v1/listenKey", headers=headers) as response:
                data = await response.json()
                self.listen_key = data.get("listenKey")
                return self.listen_key

    async def keepalive_user_data_stream(self) -> bool:
        """Giữ kết nối stream dữ liệu người dùng."""
        if self.settings.backtest_mode:
            return True
        if not self.listen_key:
            return False
        async with aiohttp.ClientSession() as session:
            headers = {"X-MBX-APIKEY": self.settings.api_key}
            async with session.put(f"{self.base_url}/fapi/v1/listenKey", params={"listenKey": self.listen_key}, headers=headers) as response:
                return response.status == 200

    async def close_user_data_stream(self) -> bool:
        """Đóng stream dữ liệu người dùng."""
        if self.settings.backtest_mode:
            return True
        if not self.listen_key:
            return False
        async with aiohttp.ClientSession() as session:
            headers = {"X-MBX-APIKEY": self.settings.api_key}
            async with session.delete(f"{self.base_url}/fapi/v1/listenKey", params={"listenKey": self.listen_key}, headers=headers) as response:
                self.listen_key = None
                return response.status == 200

    async def start_websocket_stream(self):
        """Bắt đầu stream WebSocket."""
        if self.settings.backtest_mode:
            print("Stream WebSocket không khả dụng trong chế độ backtest")
            return
        if not self.listen_key:
            await self.start_user_data_stream()
        ws_url = f"{self.ws_base_url}/ws/{self.listen_key}"
        try:
            async with websockets.connect(ws_url) as websocket:
                self.websocket = websocket
                print("Kết nối WebSocket đã mở")
                async for message in websocket:
                    data = json.loads(message)
                    event_type = data.get("e")
                    self.dispatcher.dispatch(event_type, data)
        except Exception as e:
            print(f"Lỗi WebSocket: {e}")
            self.listen_key = None

    async def keepalive_websocket_stream(self):
        """Giữ kết nối WebSocket bằng cách gửi yêu cầu keepalive định kỳ."""
        if self.settings.backtest_mode:
            return
        while self.listen_key:
            if await self.keepalive_user_data_stream():
                print("Giữ kết nối thành công")
            else:
                print("Giữ kết nối thất bại")
                self.listen_key = None
                break
            await asyncio.sleep(1800)  # Gửi keepalive mỗi 30 phút

    async def close_websocket_stream(self):
        """Đóng kết nối WebSocket."""
        if self.settings.backtest_mode:
            return
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        await self.close_user_data_stream()

    async def simulate_backtest_events(self, file_path: str):
        """Giả lập sự kiện từ dữ liệu mock trong chế độ backtest."""
        if not self.settings.backtest_mode:
            return
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                # Giả lập sự kiện ACCOUNT_UPDATE
                account_data = data.get("account", {})
                event_data = {"e": "ACCOUNT_UPDATE", "a": {"B": account_data, "P": data.get("positions", [])}}
                self.dispatcher.dispatch("ACCOUNT_UPDATE", event_data)
                # Giả lập sự kiện ORDER_TRADE_UPDATE
                for order in data.get("orders", []):
                    order_event = {"e": "ORDER_TRADE_UPDATE", "o": order}
                    self.dispatcher.dispatch("ORDER_TRADE_UPDATE", order_event)
                    await asyncio.sleep(1)  # Giả lập độ trễ
        except Exception as e:
            print(f"Lỗi khi giả lập sự kiện backtest: {e}")