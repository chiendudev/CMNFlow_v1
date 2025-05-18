from typing import List, Dict
from aiohttp import ClientSession

from config.settings import Settings
from exchange.rest_api.Klines_data import KlineModel, AggTradesSum
from exchange.rest_api.market import MarketRestAPI
from trading.enums import KlineIntervals


class MultiTimeFrameKline:
    def __init__(self, symbol: str, base_timeframe: KlineIntervals, target_timeframes: List[KlineIntervals] = None):
        self.symbol = symbol
        self.base_timeframe = base_timeframe
        self.target_timeframes = target_timeframes or []
        self.kline_data: Dict[str, List[KlineModel]] = {}

    async def fetch_klines(self, session: ClientSession, settings: Settings, start_time: str, end_time: str):
        market_rest = MarketRestAPI(session=session, settings=settings, max_weight_per_minute=1200)
        base_klines: List[KlineModel] = await market_rest.fetch_historical_klines(
            symbol=self.symbol,
            interval=self.base_timeframe,
            start_time=start_time,
            end_time=end_time
        )

        for k in base_klines:
            arr_agg_trade_sum: List[AggTradesSum] = await market_rest.fetch_historical_agg_trades(
                symbol=self.symbol,
                start_time=k.open_time,
                end_time=k.close_time,
                total_trades=k.num_trades
            )
            k.recent_trades = arr_agg_trade_sum
            self.update_single_kline(kline=k)
            print('x' * 50)
            for i, v in self.kline_data.items():
                print(f'{i} - {v}')
            print('x' * 50)


    def update_single_kline(self, kline: KlineModel, only_if_closed: bool = False):
        tf_key = self.base_timeframe.value
        if tf_key not in self.kline_data:
            self.kline_data[tf_key] = []

        klines = self.kline_data[tf_key]
        found = False

        for i, existing_kline in enumerate(klines):
            if existing_kline.open_time == kline.open_time:
                klines[i] = kline  # cập nhật nến hiện tại (chưa đóng hoặc vừa khớp)
                found = True
                break

        if not found:
            klines.append(kline)  # thêm nến mới
            klines.sort(key=lambda k: k.open_time)

        if not only_if_closed or kline.is_close:
            self._generate_higher_timeframes()

    def _generate_higher_timeframes(self):
        base_key = self.base_timeframe.value
        base_klines = self.kline_data.get(base_key, [])
        for tf in self.target_timeframes:
            minutes = self._parse_timeframe_to_minutes(tf)
            self.kline_data[tf.value] = self.aggregate_klines(base_klines, minutes)

    def aggregate_klines(self, klines: List[KlineModel], interval_minutes: int) -> List[KlineModel]:
        if not klines:
            return []

        aggregated = []
        current_group = []
        current_start = (klines[0].open_time // (interval_minutes * 60_000)) * (interval_minutes * 60_000)

        for kline in klines:
            bucket_start = (kline.open_time // (interval_minutes * 60_000)) * (interval_minutes * 60_000)
            if bucket_start != current_start:
                if current_group:
                    aggregated.append(self._merge_klines(current_group))
                current_group = []
                current_start = bucket_start
            current_group.append(kline)

        if current_group:
            aggregated.append(self._merge_klines(current_group))

        return aggregated

    def _merge_klines(self, group: List[KlineModel]) -> KlineModel:
        first = group[0]
        last = group[-1]
        return KlineModel(
            open_time=first.open_time,
            close_time=last.close_time,
            open=first.open,
            high=max(k.high for k in group),
            low=min(k.low for k in group),
            close=last.close,
            volume=sum(k.volume for k in group),
            quote_volume=sum(k.quote_volume for k in group),
            num_trades=sum(k.num_trades for k in group),
            taker_buy_base_asset_volume=sum(k.taker_buy_base_asset_volume for k in group),
            taker_buy_quote_asset_volume=sum(k.taker_buy_quote_asset_volume for k in group),
            recent_trades=[t for k in group for t in k.recent_trades],
            is_close=all(k.is_close for k in group)
        )

    @staticmethod
    def _parse_timeframe_to_minutes(tf: str) -> int:
        if tf.endswith("m"):
            return int(tf[:-1])
        elif tf.endswith("h"):
            return int(tf[:-1]) * 60
        elif tf.endswith("d"):
            return int(tf[:-1]) * 1440
        elif tf.endswith("w"):
            return int(tf[:-1]) * 10080
        elif tf.endswith("M"):
            return int(tf[:-1]) * 43200
        else:
            raise ValueError(f"Unknown timeframe format: {tf}")

    def get_klines(self, timeframe: str) -> List[KlineModel]:
        return self.kline_data.get(timeframe, [])
