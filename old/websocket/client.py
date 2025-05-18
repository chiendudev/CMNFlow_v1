from typing import List, Dict
from old.config.settings import Settings
from old.data import Kline
from old.exchange.rest_api.market import MarketRestAPI
from old.indicators import TechnicalIndicators
from old.trading.portfolio import PortfolioManager
from old.trading.enums import OrderSide, PositionSide, OrderStatus, TradeMode, KlineIntervals
from old.trading.orders import NewOrder
import aiohttp
import json
import logging
import time
from datetime import datetime
from asyncio_throttle import Throttler
from collections import deque

logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, settings: Settings, storage, portfolio: PortfolioManager):
        self.settings = settings
        self.storage = storage
        self.portfolio = portfolio
        self.confluence_zones: Dict[str, List[Dict]] = {symbol: [] for symbol in settings.symbols}
        self.throttler = Throttler(rate_limit=int(1/self.settings.throttle_rate), period=1.0)
        self.last_analysis: Dict[str, float] = {symbol: 0.0 for symbol in settings.symbols}

    async def process_aggtrade(self, symbol: str, trade: Dict):
        async with self.throttler:
            price = float(trade["p"])
            quantity = float(trade["q"])
            timestamp_ms = trade["T"]
            is_maker = trade["m"]
            for timeframe in self.settings.timeframes:
                open_time = self.round_time(timestamp_ms, timeframe)
                close_time = self.get_close_time(open_time, timeframe)
                if timeframe not in self.storage.kline_data[symbol]:
                    self.storage.kline_data[symbol][timeframe] = deque(maxlen=self.settings.max_klines)
                if not self.storage.kline_data[symbol][timeframe] or self.storage.kline_data[symbol][timeframe][-1].open_time != open_time:
                    new_kline = Kline(open_time, price, close_time, self.settings, symbol)
                    new_kline.update(price, quantity, is_maker, timestamp_ms)
                    self.storage.kline_data[symbol][timeframe].append(new_kline)
                else:
                    self.storage.kline_data[symbol][timeframe][-1].update(price, quantity, is_maker, timestamp_ms)
                self.storage.save(symbol, timeframe)
            self.portfolio.exchange_client.set_mark_price(symbol, price)
            await self.portfolio.update_all_positions(price, symbol)

    def find_confluence_zones(self, symbol: str):
        self.confluence_zones[symbol] = []
        all_zones = []
        for timeframe in self.settings.timeframes:
            if self.storage.kline_data[symbol][timeframe]:
                kline = self.storage.kline_data[symbol][timeframe][-1]
                zones, _, _, _, _ = kline.technical.analyze_zones(timeframe)
                for zone in zones:
                    all_zones.append((zone, timeframe))
        for i, (zone1, tf1) in enumerate(all_zones):
            matches = [(zone1, tf1)]
            for j, (zone2, tf2) in enumerate(all_zones):
                if i != j and abs(zone1["center_price"] - zone2["center_price"]) <= zone1["center_price"] * self.settings.confluence_range_pct:
                    matches.append((zone2, tf2))
            if len(matches) > 1:
                center_price = sum(z["center_price"] for z, _ in matches) / len(matches)
                total_volume = sum(z["total_volume"] for z, _ in matches)
                total_trades = sum(z["trades"] for z, _ in matches)
                maker_ratio = sum(z["maker_ratio"] * z["total_volume"] for z, _ in matches) / total_volume
                reliability = sum(z["reliability"] for z, _ in matches) / len(matches) + 0.2 * (len(matches) - 1)
                zone_type = max(set(z["type"] for z, _ in matches), key=lambda x: sum(1 for z, _ in matches if z["type"] == x))
                self.confluence_zones[symbol].append({
                    "center_price": round(center_price, self.settings.price_precision),
                    "timeframes": [tf for _, tf in matches],
                    "total_volume": total_volume,
                    "total_trades": total_trades,
                    "maker_ratio": maker_ratio,
                    "type": zone_type,
                    "reliability": min(1.0, reliability)
                })
        self.storage.confluence_zones[symbol] = self.confluence_zones[symbol]

    def round_time(self, timestamp_ms: int, timeframe: str) -> int:
        timestamp_s = timestamp_ms // 1000
        if timeframe.endswith("m"):
            minutes = int(timeframe[:-1])
            interval_s = minutes * 60
        elif timeframe.endswith("h"):
            hours = int(timeframe[:-1])
            interval_s = hours * 3600
        else:
            raise ValueError(f"Khung thời gian không hỗ trợ: {timeframe}")
        rounded_s = (timestamp_s // interval_s) * interval_s
        return rounded_s * 1000

    def get_close_time(self, open_time: int, timeframe: str) -> int:
        if timeframe.endswith("m"):
            minutes = int(timeframe[:-1])
            interval_ms = minutes * 60 * 1000
        elif timeframe.endswith("h"):
            hours = int(timeframe[:-1])
            interval_ms = hours * 3600 * 1000
        else:
            raise ValueError(f"Khung thời gian không hỗ trợ: {timeframe}")
        return open_time + interval_ms - 1

    async def process_trade_signal(self, signal: Dict):
        logger.info("Xử lý gợi ý giao dịch cho %s: %s", signal["symbol"], signal)
        side = OrderSide.BUY if signal["type"] == "buy" else OrderSide.SELL
        position_side = PositionSide.BOTH if self.settings.trade_mode == TradeMode.ONE_WAY else \
            PositionSide.LONG if signal["type"] == "buy" else PositionSide.SHORT
        order = NewOrder(
            symbol=signal["symbol"],
            side=side,
            position_side=position_side,
            quantity=self.settings.trade_quantity,
            price=signal["entry"],
            status=OrderStatus.FILLED,
            executed_qty=self.settings.trade_quantity,
            avg_price=signal["entry"],
            fee=self.settings.trade_quantity * signal["entry"] * self.portfolio.exchange_client.get_commission_rate(
                signal["symbol"]),
            reduce_only=False
        )
        logger.debug("Tạo lệnh mới: %s", order.__dict__)
        await self.portfolio.process_new_order(order)
        logger.debug("Sau khi xử lý lệnh, portfolio.positions: %s", self.portfolio.positions)
        if self.settings.use_sl_tp:
            take_profits = [(signal["take_profit"], self.settings.trade_quantity, False, 0.0, 'fixed', 0.0)] if signal[
                "take_profit"] else []
            stop_losses = [(signal["stop_loss"], self.settings.trade_quantity, False, 0.0, 'fixed', 0.0)] if signal[
                "stop_loss"] else []
            await self.portfolio.set_tp_sl(
                symbol=signal["symbol"],
                position_side=position_side,
                take_profits=take_profits,
                stop_losses=stop_losses
            )
            logger.debug("Đã thiết lập SL/TP: TP=%s, SL=%s", take_profits, stop_losses)
        self.storage.positions_data[signal["symbol"]].append({
            "timestamp": time.time(),
            "signal": signal,
            "order": {
                "symbol": order.symbol,
                "side": order.side.value,
                "position_side": order.position_side.value,
                "quantity": order.quantity,
                "price": order.price,
                "fee": order.fee
            },
            "sl_tp": {
                "take_profit": signal.get("take_profit"),
                "stop_loss": signal.get("stop_loss")
            }
        })
        logger.debug("Đã lưu dữ liệu vị thế vào storage: %s", self.storage.positions_data[signal["symbol"]])
        self.portfolio.summary()

    async def run(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.settings.ws_url) as ws:
                streams = [f"{symbol.lower()}@aggTrade" for symbol in self.settings.symbols]
                await ws.send_json({
                    "method": "SUBSCRIBE",
                    "params": streams,
                    "id": 1
                })
                logger.info("Kết nối WebSocket thành công, đã đăng ký: %s", streams)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if "stream" in data and "data" in data:
                            symbol = next(s for s in self.settings.symbols if s.lower() in data["stream"]).upper()
                            await self.process_aggtrade(symbol, data["data"])
                            current_time = time.time()
                            if current_time - self.last_analysis[symbol] >= 10:
                                self.find_confluence_zones(symbol)
                                for timeframe in self.settings.timeframes:
                                    if self.storage.kline_data[symbol][timeframe]:
                                        kline = self.storage.kline_data[symbol][timeframe][-1]
                                        if len(kline.close_history) < max(self.settings.rsi_period, self.settings.ema_slow_period):
                                            logger.debug("[%s][%s] Chưa đủ dữ liệu để tính toán indicators (%d/%d)",
                                                         symbol, timeframe, len(kline.close_history), max(self.settings.rsi_period, self.settings.ema_slow_period))
                                            continue
                                        kline.technical.calculate()
                                        open_time = datetime.utcfromtimestamp(kline.open_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
                                        zones, _, _, poc_price, value_area = kline.technical.analyze_zones(timeframe)
                                        signals = kline.technical.generate_signals(timeframe, self.confluence_zones[symbol])
                                        logger.info("[%s][%s] Open Time: %s, OHLCV: %.2f, %.2f, %.2f, %.2f, Volume: %.2f",
                                                    symbol, timeframe, open_time, kline.open, kline.high, kline.low, kline.close, kline.volume)
                                        if all(v is not None for v in [kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow]):
                                            logger.info("[%s][%s] Technicals: RSI=%.1f, ATR=%.2f, EMA9=%.2f, EMA21=%.2f",
                                                        symbol, timeframe, kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow)
                                        else:
                                            logger.debug("[%s][%s] Indicators chưa sẵn sàng: RSI=%s, ATR=%s, EMA9=%s, EMA21=%s",
                                                         symbol, timeframe, kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow)
                                        logger.info("[%s][%s] POC: %s, Value Area: %s", symbol, timeframe, poc_price, value_area)
                                        for zone in zones:
                                            logger.info("[%s][%s] Zone: Price=%.2f, Range=%s, Volume=%.2f, Trades=%d, MakerRatio=%.2f, Type=%s, Depth=%.2f, BreakoutProb=%.2f, Reliability=%.2f",
                                                        symbol, timeframe, zone["center_price"], zone["price_range"], zone["total_volume"], zone["trades"],
                                                        zone["maker_ratio"], zone["type"], zone["depth"], zone["breakout_probability"], zone["reliability"])
                                        for signal in signals:
                                            logger.info("[%s][%s] Trade Signal: %s at %.2f, SL=%.2f, TP=%.2f, R/R=%.2f, StopHuntRisk=%.2f, Reason=%s",
                                                        signal["symbol"], signal["timeframe"], signal["type"].upper(), signal["entry"], signal["stop_loss"],
                                                        signal["take_profit"], signal["risk_reward_ratio"], signal["stop_hunt_risk"], signal["reason"])
                                            await self.process_trade_signal(signal)
                                        stop_hunt = kline.technical.detect_stop_hunt(timeframe, [z["center_price"] for z in zones])
                                        if stop_hunt:
                                            logger.info("[%s][%s] STOP HUNT DETECTED: Price=%.2f, Direction=%s, Volume=%.2f, TakerRatio=%.2f, PriceMove=%.4f, RSI=%.1f",
                                                        symbol, timeframe, stop_hunt["target_price"], stop_hunt["direction"], stop_hunt["volume"],
                                                        stop_hunt["taker_ratio"], stop_hunt["price_move"], stop_hunt["technical_indicators"]["rsi"])
                                            self.storage.stop_hunt_events[symbol].append(stop_hunt)
                                if self.confluence_zones[symbol]:
                                    logger.info("[%s] Confluence Zones:", symbol)
                                    for zone in self.confluence_zones[symbol]:
                                        logger.info("[%s] Price=%.2f, Timeframes=%s, Volume=%.2f, Trades=%d, MakerRatio=%.2f, Type=%s, Reliability=%.2f",
                                                    symbol, zone["center_price"], zone["timeframes"], zone["total_volume"], zone["total_trades"],
                                                    zone["maker_ratio"], zone["type"], zone["reliability"])
                                self.last_analysis[symbol] = current_time
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.info("WebSocket đã đóng.")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error("Lỗi WebSocket: %s", msg)
                        break
                await self.storage.save_all()

    async def process_historical_data(self, symbol: str, start_date: str, end_date: str, timeframe: str = "5m"):
        """Process historical data from MarketRestAPI"""
        async with aiohttp.ClientSession() as session:
            market_rest = MarketRestAPI(session=session, settings=self.settings, max_weight_per_minute=1200)
            try:
                # Fetch klines
                klines = await market_rest.fetch_historical_klines(symbol, KlineIntervals.m5, start_date, end_date)
                if not klines:
                    logger.error("No klines returned for %s", symbol)
                    return
                logger.debug("Fetched %d klines for %s", len(klines), symbol)

                # Validate kline format
                for k in klines:
                    if not isinstance(k, (list, tuple)) or len(k) < 7:
                        logger.error("Invalid kline format: %s", k)
                        continue

                # Initialize kline_data
                if symbol not in self.storage.kline_data:
                    self.storage.kline_data[symbol] = {}
                if timeframe not in self.storage.kline_data[symbol]:
                    self.storage.kline_data[symbol][timeframe] = deque(maxlen=self.settings.max_klines)

                # Clear existing klines to avoid duplicates
                self.storage.kline_data[symbol][timeframe].clear()

                for k in klines:
                    try:
                        open_time = int(k[0])
                        close_price = float(k[4])
                        volume = float(k[5])
                        close_time = int(k[6])
                    except (TypeError, ValueError) as e:
                        logger.error("Error parsing kline: %s, error: %s", k, e)
                        continue

                    # Create new Kline for each kline data
                    kline = Kline(
                        open_time=open_time,
                        price=float(k[1]),  # Use open price as initial price
                        close_time=close_time,
                        settings=self.settings,
                        symbol=symbol
                    )
                    kline.open = float(k[1])
                    kline.high = float(k[2])
                    kline.low = float(k[3])
                    kline.close = close_price
                    kline.volume = volume
                    kline.technical = TechnicalIndicators(kline, self.settings)
                    self.storage.kline_data[symbol][timeframe].append(kline)

                    # Update price histories
                    kline.close_history.append(close_price)
                    kline.high_history.append(float(k[2]))
                    kline.low_history.append(float(k[3]))

                    # Fetch agg_trades
                    agg_trades = await market_rest.fetch_historical_agg_trades(symbol, start_time=open_time, end_time=close_time)
                    if not agg_trades:
                        logger.warning("No agg trades for %s at %d", symbol, open_time)
                        continue

                    # Calculate total quantity and update price_qty
                    total_quantity = 0
                    price_qty = {}
                    for trade in agg_trades:
                        price = float(trade['p'])
                        quantity = float(trade['q'])
                        is_maker = trade['m']
                        total_quantity += quantity
                        if price not in price_qty:
                            price_qty[price] = {"maker_qty": 0, "taker_qty": 0, "count": 0}
                        if is_maker:
                            price_qty[price]["maker_qty"] += quantity
                        else:
                            price_qty[price]["taker_qty"] += quantity
                        price_qty[price]["count"] += 1
                    kline.price_qty = price_qty

                    logger.info("Kline volume: %.2f, Agg trades volume: %.2f", volume, total_quantity)
                    for trade in agg_trades:
                        logger.debug("Trade: %s", trade)

                    # Update recent_trades
                    kline.recent_trades = [
                        {
                            "price": float(trade['p']),
                            "quantity": float(trade['q']),
                            "is_maker": trade['m'],
                            "timestamp_ms": trade['T']
                        } for trade in agg_trades
                    ]

                # Process analysis after all klines are created
                current_time = time.time()
                if current_time - self.last_analysis[symbol] >= 10:
                    self.find_confluence_zones(symbol)
                    for tf in self.settings.timeframes:
                        if self.storage.kline_data[symbol][tf]:
                            kline = self.storage.kline_data[symbol][tf][-1]
                            if len(kline.close_history) < max(self.settings.rsi_period, self.settings.ema_slow_period):
                                logger.debug("[%s][%s] Not enough data to calculate indicators (%d/%d)",
                                             symbol, tf, len(kline.close_history), max(self.settings.rsi_period, self.settings.ema_slow_period))
                                continue
                            kline.technical.calculate()
                            open_time_dt = datetime.utcfromtimestamp(kline.open_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
                            zones, _, _, poc_price, value_area = kline.technical.analyze_zones(tf)
                            signals = kline.technical.generate_signals(tf, self.confluence_zones[symbol])
                            logger.info("[%s][%s] Open Time: %s, OHLCV: %.2f, %.2f, %.2f, %.2f, Volume: %.2f",
                                        symbol, tf, open_time_dt, kline.open, kline.high, kline.low, kline.close, kline.volume)
                            if all(v is not None for v in [kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow]):
                                logger.info("[%s][%s] Technicals: RSI=%.1f, ATR=%.2f, EMA9=%.2f, EMA21=%.2f",
                                            symbol, tf, kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow)
                            else:
                                logger.debug("[%s][%s] Indicators not ready: RSI=%s, ATR=%s, EMA9=%s, EMA21=%s",
                                             symbol, tf, kline.technical.rsi, kline.technical.atr, kline.technical.ema_fast, kline.technical.ema_slow)
                            logger.info("[%s][%s] POC: %s, Value Area: %s", symbol, tf, poc_price, value_area)
                            for zone in zones:
                                logger.info("[%s][%s] Zone: Price=%.2f, Range=%s, Volume=%.2f, Trades=%d, MakerRatio=%.2f, Type=%s, Depth=%.2f, BreakoutProb=%.2f, Reliability=%.2f",
                                            symbol, tf, zone["center_price"], zone["price_range"], zone["total_volume"], zone["trades"],
                                            zone["maker_ratio"], zone["type"], zone["depth"], zone["breakout_probability"], zone["reliability"])
                            for signal in signals:
                                logger.info("[%s][%s] Trade Signal: %s at %.2f, SL=%.2f, TP=%.2f, R/R=%.2f, StopHuntRisk=%.2f, Reason=%s",
                                            signal["symbol"], signal["timeframe"], signal["type"].upper(), signal["entry"], signal["stop_loss"],
                                            signal["take_profit"], signal["risk_reward_ratio"], signal["stop_hunt_risk"], signal["reason"])
                                await self.process_trade_signal(signal)
                            stop_hunt = kline.technical.detect_stop_hunt(tf, [z["center_price"] for z in zones])
                            if stop_hunt:
                                logger.info("[%s][%s] STOP HUNT DETECTED: Price=%.2f, Direction=%s, Volume=%.2f, TakerRatio=%.2f, PriceMove=%.4f, RSI=%.1f",
                                            symbol, tf, stop_hunt["target_price"], stop_hunt["direction"], stop_hunt["volume"],
                                            stop_hunt["taker_ratio"], stop_hunt["price_move"], stop_hunt["technical_indicators"]["rsi"])
                                self.storage.stop_hunt_events[symbol].append(stop_hunt)
                    if self.confluence_zones[symbol]:
                        logger.info("[%s] Confluence Zones:", symbol)
                        for zone in self.confluence_zones[symbol]:
                            logger.info("[%s] Price=%.2f, Timeframes=%s, Volume=%.2f, Trades=%d, MakerRatio=%.2f, Type=%s, Reliability=%.2f",
                                        symbol, zone["center_price"], zone["timeframes"], zone["total_volume"], zone["total_trades"],
                                        zone["maker_ratio"], zone["type"], zone["reliability"])
                    self.last_analysis[symbol] = current_time
            except Exception as e:
                logger.error("Error processing historical data: %s", e)
                raise