# tests/test_integration.py
import pytest
import asyncio
import logging
import os
from config.settings import Settings
from data.storage import DataStorage
from exchange.binance_client import BinanceClient
from trading.portfolio import PortfolioManager
from trading.enums import TradeMode, MarginType, PositionSide
from websocket.client import WebSocketClient

# Cấu hình logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # In ra console
        logging.FileHandler(os.path.join(log_dir, 'app.log'))  # Lưu vào tệp logs/app.log
    ]
)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
class TestIntegration:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.settings = Settings()
        self.storage = DataStorage(self.settings)
        self.client = BinanceClient(self.settings.api_key, self.settings.api_secret)
        self.portfolio = PortfolioManager(TradeMode.ONE_WAY, MarginType.ISOLATED, self.settings.leverage)
        self.portfolio.set_exchange_client(self.client)
        self.ws_client = WebSocketClient(self.settings, self.storage, self.portfolio)

    async def test_process_trade_signal(self):
        signal = {
            "symbol": "BTCUSDT",
            "type": "buy",
            "entry": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 52000.0,
            "timeframe": "1m",
            "risk_reward_ratio": 2.0,
            "stop_hunt_risk": 0.0,
            "reason": "Price near support zone"
        }
        logger.debug("Bắt đầu xử lý tín hiệu: %s", signal)
        await self.ws_client.process_trade_signal(signal)
        assert len(self.storage.positions_data["BTCUSDT"]) == 1, "Dữ liệu vị thế phải được lưu"
        stored_position = self.storage.positions_data["BTCUSDT"][0]
        assert stored_position["signal"] == signal, "Tín hiệu lưu trữ phải khớp"
        assert stored_position["order"]["price"] == signal["entry"], "Giá lệnh lưu trữ phải khớp"
        position_key = ("BTCUSDT", PositionSide.BOTH)
        position = self.portfolio.positions.get(position_key)
        assert position is not None, "Vị thế phải được tạo"
        assert position["quantity"] == self.settings.trade_quantity, "Số lượng vị thế phải khớp"
        logger.debug("Vị thế: %s", position)
        assert position["entry_price"] == signal["entry"], "Giá vào lệnh phải khớp"
        if self.settings.use_sl_tp:
            assert position["stop_losses"][0][0] == signal["stop_loss"], "Stop loss phải khớp"
            assert position["take_profits"][0][0] == signal["take_profit"], "Take profit phải khớp"