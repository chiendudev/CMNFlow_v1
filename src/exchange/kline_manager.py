from typing import Dict, List
from collections import deque
import logging
from aiohttp import ClientSession
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.settings import Settings
from src.data.kline import Kline
from src.data.trade import Trade, TradeSummary
from src.exchange.client import ExchangeClient
from src.trading.enums import KlineIntervals

logger = logging.getLogger(__name__)

class KlineManager:
    def __init__(self, symbol: str, settings: Settings):
        self.symbol = symbol
        self.settings = settings
        self.timeframes = [KlineIntervals(tf) for tf in settings.timeframes]
        self.base_timeframe = KlineIntervals(settings.base_timeframe)
        self.klines: Dict[str, deque[Kline]] = {
            tf.value: deque(maxlen=settings.max_klines) for tf in self.timeframes
        }
        self.max_trades_per_kline = 1000

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_historical(self, exchange: ExchangeClient, start_time: str, end_time: str) -> None:
        """Fetch historical klines and trades."""
        klines = await exchange.fetch_klines(self.symbol, self.base_timeframe, start_time, end_time)
        for kline in klines:
            kline.trades = await exchange.fetch_trades(self.symbol, kline.open_time, kline.close_time)
            kline.trades = kline.trades[:self.max_trades_per_kline]
            kline.num_trades = sum(t.num_trades for t in kline.trades)
        self.klines[self.base_timeframe.value].extend(klines)
        self._aggregate_higher_timeframes()
        logger.info("Fetched %d klines for %s in %s", len(klines), self.symbol, self.base_timeframe.value)

    async def update(self, trade: Trade) -> None:
        """Update klines with a new trade."""
        for tf in self.timeframes:
            tf_key = tf.value
            open_time = self._round_time(trade.timestamp, tf)
            close_time = self._get_close_time(open_time, tf)
            klines = self.klines[tf_key]
            kline = next((k for k in klines if k.open_time == open_time), None)

            if not kline:
                kline = Kline(
                    symbol=self.symbol,
                    timeframe=tf_key,
                    open_time=open_time,
                    close_time=close_time,
                    open=trade.price,
                    high=trade.price,
                    low=trade.price,
                    close=trade.price
                )
                klines.append(kline)

            kline.update(trade.price, trade.qty, (trade.last_id + 1) - trade.first_id)
            trade_sum = next((t for t in kline.trades if t.price == trade.price), None)
            if not trade_sum:
                trade_sum = TradeSummary(price=trade.price, last_update=trade.timestamp)
                kline.trades.append(trade_sum)
            trade_sum.update(trade)
            kline.trades = kline.trades[-self.max_trades_per_kline:]
            kline.is_closed = trade.timestamp >= close_time

            if tf == self.base_timeframe and kline.is_closed:
                self._aggregate_higher_timeframes()

    def _aggregate_higher_timeframes(self) -> None:
        base_key = self.base_timeframe.value
        base_klines = list(self.klines[base_key])
        for tf in self.timeframes:
            if tf == self.base_timeframe:
                continue
            tf_key = tf.value
            minutes = self._parse_timeframe_to_minutes(tf)
            buckets: Dict[int, List[Kline]] = {}
            for kline in base_klines:
                bucket_start = (kline.open_time // (minutes * 60_000)) * (minutes * 60_000)
                buckets.setdefault(bucket_start, []).append(kline)

            aggregated = []
            for bucket_start, group in buckets.items():
                aggregated.append(self._merge_klines(group, tf_key, bucket_start))
            self.klines[tf_key].clear()
            self.klines[tf_key].extend(sorted(aggregated, key=lambda k: k.open_time))

    def _merge_klines(self, group: List[Kline], timeframe: str, bucket_start: int) -> Kline:
        first = group[0]
        last = group[-1]
        kline = Kline(
            symbol=self.symbol,
            timeframe=timeframe,
            open_time=bucket_start,
            close_time=self._get_close_time(bucket_start, timeframe),
            open=first.open,
            high=max(k.high for k in group),
            low=min(k.low for k in group),
            close=last.close,
            volume=sum(k.volume for k in group),
            num_trades=sum(k.num_trades for k in group),
            is_closed=all(k.is_closed for k in group)
        )
        trade_dict: Dict[float, TradeSummary] = {}
        for k in group:
            for t in k.trades:
                if t.price not in trade_dict:
                    trade_dict[t.price] = TradeSummary(price=t.price, last_update=t.last_update)
                trade_dict[t.price].maker_qty += t.maker_qty
                trade_dict[t.price].taker_qty += t.taker_qty
                trade_dict[t.price].total_qty += t.total_qty
                trade_dict[t.price].num_trades += t.num_trades
        kline.trades = list(trade_dict.values())[:self.max_trades_per_kline]
        return kline

    def get_klines(self, timeframe: str) -> List[Kline]:
        return list(self.klines.get(timeframe, []))

    @staticmethod
    def _parse_timeframe_to_minutes(tf: KlineIntervals) -> int:
        tf_str = tf.value
        if tf_str.endswith("m"):
            return int(tf_str[:-1])
        elif tf_str.endswith("h"):
            return int(tf_str[:-1]) * 60
        raise ValueError(f"Unsupported timeframe: {tf_str}")

    def _round_time(self, timestamp_ms: int, timeframe: KlineIntervals) -> int:
        timestamp_s = timestamp_ms // 1000
        interval_s = self._parse_timeframe_to_minutes(timeframe) * 60
        return (timestamp_s // interval_s) * interval_s * 1000

    def _get_close_time(self, open_time: int, timeframe: KlineIntervals) -> int:
        interval_ms = self._parse_timeframe_to_minutes(timeframe) * 60 * 1000
        return open_time + interval_ms - 1