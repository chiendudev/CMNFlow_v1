import asyncio
import logging
import numpy as np
from typing import Dict, List, Optional
from src.core.settings import Settings
from src.core.storage import Storage
from src.strategy.confluence import Confluence
from src.strategy.indicators import Indicators

logger = logging.getLogger(__name__)

class Position:
    def __init__(self, symbol: str, side: str, size: float, entry_price: float, tp: Optional[float] = None, sl: Optional[float] = None):
        self.symbol = symbol
        self.side = side  # "long" or "short"
        self.size = size
        self.entry_price = entry_price
        self.tp = tp
        self.sl = sl
        self.unrealized_pnl = 0.0

    def update_pnl(self, current_price: float):
        if self.side == "long":
            self.unrealized_pnl = (current_price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.size
        return self.unrealized_pnl

class Portfolio:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.indicators = Indicators()
        self.confluence = Confluence(settings, self.indicators)
        self.equity = 10000.0  # Vốn ban đầu
        self.margin_used = 0.0
        self.positions: Dict[str, Dict[str, Position]] = {symbol: {"long": None, "short": None} for symbol in settings.symbols}
        self.grid_levels: Dict[str, List[float]] = {symbol: [] for symbol in settings.symbols}
        self.indicator_cache: Dict[str, Dict] = {symbol: {} for symbol in settings.symbols}

    async def handle_signal(self, signal: Dict):
        symbol = signal["symbol"]
        direction = signal.get("direction")
        strategy = signal.get("strategy")
        timeframe = next((tf for tf in self.settings.timeframes if f"confluence_{tf}" in signal), "5m")
        klines = [{"close": k.close, "volume": k.volume, "trades": [], "high": k.high, "low": k.low} for k in signal.get("klines", [])]
        trades = signal.get("trades", [])

        if direction == "hedge" or strategy == "hedging":
            await self.apply_hedging_strategies(symbol, timeframe, klines, trades)
        elif direction in ["buy", "sell"]:
            await self.execute_position(symbol, direction, strategy, timeframe, klines, trades)

    async def apply_hedging_strategies(self, symbol: str, timeframe: str, klines: List[Dict], trades: List[Dict]):
        confluence_result = await self.confluence.evaluate(symbol, timeframe, klines, trades)
        latest_price = klines[0]["close"] if klines else 0
        support, resistance = self.indicators.find_support_resistance(klines)

        # Cache indicators
        if symbol not in self.indicator_cache or timeframe not in self.indicator_cache[symbol]:
            self.indicator_cache[symbol][timeframe] = {}
        closes = np.array([k["close"] for k in klines], dtype=np.float64)
        atr = self.indicators.calculate_atr(klines, self.settings.atr_period)
        upper_bb, middle_bb, lower_bb = self.indicators.calculate_bollinger_bands(closes, self.settings.bb_period, self.settings.bb_std)
        self.indicator_cache[symbol][timeframe].update({"atr": atr, "upper_bb": upper_bb, "lower_bb": lower_bb})

        # 1. Dual Momentum Entry
        if confluence_result["direction"] == "none" and support and resistance:
            support_diff_pct = abs(latest_price - support) / support if support else float('inf')
            resistance_diff_pct = abs(latest_price - resistance) / resistance if resistance else float('inf')
            if support_diff_pct < self.settings.confluence_range_pct:
                await self.open_position(symbol, "long", 0.5, latest_price, tp=resistance, sl=support * 0.99)
                await self.open_position(symbol, "short", 0.5, latest_price, tp=support, sl=resistance * 1.01)
                logger.info(f"Dual Momentum Entry for {symbol}: Long near support {support}, Short near resistance {resistance}")
            elif resistance_diff_pct < self.settings.confluence_range_pct:
                await self.open_position(symbol, "long", 0.5, latest_price, tp=resistance, sl=support * 0.99)
                await self.open_position(symbol, "short", 0.5, latest_price, tp=support, sl=resistance * 1.01)
                logger.info(f"Dual Momentum Entry for {symbol}: Long near support {support}, Short near resistance {resistance}")

        # 2. Trailing One Side
        for side in ["long", "short"]:
            pos = self.positions[symbol][side]
            if pos and pos.update_pnl(latest_price) > self.equity * self.settings.profit_threshold:
                opposite_side = "short" if side == "long" else "long"
                await self.open_position(symbol, opposite_side, pos.size * 0.3, latest_price, sl=latest_price * (1.01 if opposite_side == "long" else 0.99))
                logger.info(f"Trailing One Side for {symbol}: Opened {opposite_side} to lock profit on {side}")

        # 3. Grid Hedging
        grid_spacing = self.indicator_cache[symbol][timeframe]["atr"] * self.settings.atr_multiplier
        if not self.grid_levels[symbol]:
            self.grid_levels[symbol] = [latest_price + i * grid_spacing for i in range(-5, 6)]
        for level in self.grid_levels[symbol]:
            if abs(latest_price - level) / level < 0.005:
                if latest_price > level:
                    await self.open_position(symbol, "short", 0.2, latest_price, tp=level - grid_spacing)
                else:
                    await self.open_position(symbol, "long", 0.2, latest_price, tp=level + grid_spacing)
                logger.info(f"Grid Hedging for {symbol}: Opened at {level}, grid_spacing={grid_spacing}")

        # 4. Breakout + Hedge Retest
        if any(c["type"].startswith("breakout_") for c in confluence_result["conditions"]):
            breakout_direction = "buy" if "breakout_above_resistance" in [c["type"] for c in confluence_result["conditions"]] else "sell"
            await self.open_position(symbol, "long" if breakout_direction == "buy" else "short", 0.5, latest_price)
            if breakout_direction == "buy" and latest_price <= self.indicator_cache[symbol][timeframe]["lower_bb"]:
                await self.open_position(symbol, "short", 0.3, latest_price, tp=support)
                logger.info(f"Breakout + Hedge Retest for {symbol}: Long on breakout, Short on retest at lower BB {self.indicator_cache[symbol][timeframe]['lower_bb']}")
            elif breakout_direction == "sell" and latest_price >= self.indicator_cache[symbol][timeframe]["upper_bb"]:
                await self.open_position(symbol, "long", 0.3, latest_price, tp=resistance)
                logger.info(f"Breakout + Hedge Retest for {symbol}: Short on breakout, Long on retest at upper BB {self.indicator_cache[symbol][timeframe]['upper_bb']}")

        # 5. Hedging theo Timeframe
        if timeframe in ["5m", "15m"]:
            timestamp = klines[0]["timestamp"] if klines else 0
            h4_klines = await self.storage.get_klines(symbol, "4h", start_time=int(timestamp - 24*3600*1000), end_time=timestamp)
            h4_confluence = await self.confluence.evaluate(symbol, "4h", [{"close": k.close, "volume": k.volume, "trades": [], "high": k.high, "low": k.low} for k in h4_klines], trades)
            if h4_confluence["direction"] == "buy" and confluence_result["direction"] == "sell":
                await self.open_position(symbol, "long", 0.5, latest_price, timeframe="4h")
                await self.open_position(symbol, "short", 0.3, latest_price, timeframe=timeframe)
                logger.info(f"Hedging theo Timeframe for {symbol}: Long on 4h, Short on {timeframe}")
            elif h4_confluence["direction"] == "sell" and confluence_result["direction"] == "buy":
                await self.open_position(symbol, "short", 0.5, latest_price, timeframe="4h")
                await self.open_position(symbol, "long", 0.3, latest_price, timeframe=timeframe)
                logger.info(f"Hedging theo Timeframe for {symbol}: Short on 4h, Long on {timeframe}")

    async def open_position(self, symbol: str, side: str, size: float, entry_price: float, tp: Optional[float] = None, sl: Optional[float] = None, timeframe: str = "5m"):
        if self.settings.backtest_mode:
            # Mô phỏng lệnh trong backtest
            self.positions[symbol][side] = Position(symbol, side, size, entry_price, tp, sl)
            self.margin_used += size * entry_price / self.settings.leverage
            logger.info(f"[Backtest] Opened {side} position for {symbol}: size={size}, price={entry_price}, timeframe={timeframe}")
        else:
            import ccxt.async_support as ccxt
            self.exchange = ccxt.binance({
                'apiKey': self.settings.api_key,
                'secret': self.settings.api_secret,
                'enableRateLimit': True
            })
            await self.exchange.create_market_order(symbol, side, size, params={"type": "future"})
            self.positions[symbol][side] = Position(symbol, side, size, entry_price, tp, sl)
            self.margin_used += size * entry_price / self.settings.leverage
            logger.info(f"Opened {side} position for {symbol}: size={size}, price={entry_price}, timeframe={timeframe}")

    async def execute_position(self, symbol: str, direction: str, strategy: str, timeframe: str, klines: List[Dict], trades: List[Dict]):
        latest_price = klines[0]["close"] if klines else 0
        side = "long" if direction == "buy" else "short"
        size = 0.5
        await self.open_position(symbol, side, size, latest_price, timeframe=timeframe)

    async def smart_exit(self, symbol: str, side: str, current_price: float, mode: str = "tp_sl_independent"):
        pos = self.positions[symbol][side]
        if not pos:
            return
        if mode == "tp_sl_independent":
            if pos.tp and ((side == "long" and current_price >= pos.tp) or (side == "short" and current_price <= pos.tp)):
                await self.close_position(symbol, side, pos.size)
            elif pos.sl and ((side == "long" and current_price <= pos.sl) or (side == "short" and current_price >= pos.sl)):
                await self.close_position(symbol, side, pos.size)
        elif mode == "reduce_only":
            reduce_size = pos.size * 0.3
            await self.close_position(symbol, side, reduce_size)
        elif mode == "close_position":
            await self.close_position(symbol, side, pos.size)

    async def close_position(self, symbol: str, side: str, size: float):
        pos = self.positions[symbol][side]
        if not pos:
            return
        if self.settings.backtest_mode:
            # Mô phỏng đóng lệnh trong backtest
            current_price = pos.entry_price  # Giả sử đóng tại giá hiện tại (cần lấy từ kline/trade)
            if self.storage.latest_kline:
                current_price = self.storage.latest_kline["close"]
            realized_pnl = (current_price - pos.entry_price if side == "long" else pos.entry_price - current_price) * size
            self.equity += realized_pnl
            logger.info(f"[Backtest] Closed {side} position for {symbol}: size={size}, realized_pnl={realized_pnl}")
        else:
            import ccxt.async_support as ccxt
            self.exchange = ccxt.binance({
                'apiKey': self.settings.api_key,
                'secret': self.settings.api_secret,
                'enableRateLimit': True
            })
            opposite_side = "sell" if side == "long" else "buy"
            await self.exchange.create_market_order(symbol, opposite_side, size, params={"type": "future", "reduceOnly": True})
            logger.info(f"Closed {side} position for {symbol}: size={size}")

        if pos.size <= size:
            self.positions[symbol][side] = None
        else:
            pos.size -= size
        self.margin_used -= size * pos.entry_price / self.settings.leverage

    async def run(self):
        while True:
            for symbol in self.settings.symbols:
                for side in ["long", "short"]:
                    if self.positions[symbol][side]:
                        latest_price = self.storage.latest_kline["close"] if self.storage.latest_kline else 0
                        if not self.settings.backtest_mode:
                            import ccxt.async_support as ccxt
                            self.exchange = ccxt.binance({
                                'apiKey': self.settings.api_key,
                                'secret': self.settings.api_secret,
                                'enableRateLimit': True
                            })
                            latest_price = (await self.exchange.fetch_ticker(symbol))["last"]
                        await self.smart_exit(symbol, side, latest_price)
            await asyncio.sleep(self.settings.throttle_rate)