import aiohttp
import asyncio
from aiolimiter import AsyncLimiter
from typing import Optional, Dict, Any, Union, List
from exchange.rest_api.base_model_symbol_info import ContractInfo
from config.settings import Settings
from trading.enums import KlineIntervals
from datetime import datetime, timedelta
from exchange.rest_api.Klines_data import AggTradeModel, AggTradesSum, KlineModel
from pydantic import ValidationError

def to_milliseconds(dt: Union[str, int], end_of_day: bool = False) -> int:
    if isinstance(dt, int):
        return dt

    dt_obj = datetime.strptime(dt, "%d/%m/%Y")
    if end_of_day:
        # Cộng 1 ngày rồi trừ 1 ms để ra 23:59:59.999 của ngày dt
        dt_obj = dt_obj - timedelta(milliseconds=1)
    return int(dt_obj.timestamp() * 1000)

class MarketRestAPI:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        settings: Settings,
        max_weight_per_minute: int = 1200
    ):
        self.base_url = settings.rest_api_url
        self.session = session
        self.settings = settings
        self.limiter = AsyncLimiter(max_rate=max_weight_per_minute, time_period=60)

    async def _request(
            self,
            method: str,
            path: str,
            params: Optional[Dict[str, Any]] = None,
            weight: int = 1
    ) -> Any:
        url = f"{self.base_url}{path}"

        # Thay vì dùng async with, bạn gọi acquire() nhiều lần tùy weight
        for _ in range(weight):
            await self.limiter.acquire()

        async with self.session.request(method, url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"❌ Request failed [{resp.status}]: {text}")
            return await resp.json()

    # ================================
    # Các method tiện ích cụ thể dưới đây
    # ================================

    async def exchange_info(self) -> Dict[str, ContractInfo]:
        url = f'{self.base_url}/fapi/v1/exchangeInfo'
        async with self.session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()

            symbols_exchange_info: Dict[str, ContractInfo] = {}
            if 'symbols' in data:
                for symbol_data in data['symbols']:
                    try:
                        model = ContractInfo.model_validate(symbol_data)
                        symbols_exchange_info[model.symbol] = model
                    except Exception as e:
                        # Nếu cần debug chi tiết
                        print(f"❌ Lỗi parse symbol {symbol_data.get('symbol')}: {e}")

            return symbols_exchange_info

    async def fetch_historical_agg_trades(
            self,
            symbol: str,
            start_time: Optional[int] = None,
            end_time: Optional[int] = None,
            from_id: Optional[int] = None,
            to_id: Optional[int] = None,
            limit: int = 1000,
            total_trades: Optional[int] = None
    ) -> List[AggTradesSum]:

        if limit < 1 or limit > 1000:
            raise ValueError("Limit must be between 1 and 1000")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Invalid time range: start_time must be <= end_time")

        if (start_time or end_time) and (from_id or to_id):
            print("Warning: Both time and ID parameters provided; prioritizing ID-based fetching")

        # === Calculate from_id if only start_time + total_trades provided ===
        if from_id is None and total_trades is not None and start_time is not None:
            first = await self._request("GET", "/fapi/v1/aggTrades", {
                "symbol": symbol,
                "startTime": start_time - 1,
                "limit": 1
            }, weight=20)
            if not first:
                raise ValueError("No trades found at start_time")

            from_id = first[0]['a']

        all_trades: List[AggTradesSum] = []
        retries: int = 3
        sleep_duration: float = 0.2
        current_id = from_id
        real_trades_fetched = 0
        total_qty_raw = 0.0

        while True:
            remaining_needed = total_trades - real_trades_fetched if total_trades else limit
            fetch_limit = min(limit, remaining_needed) if total_trades else limit

            params = {"symbol": symbol, "limit": fetch_limit, "fromId": current_id}

            for attempt in range(retries):
                try:
                    trades = await self._request("GET", "/fapi/v1/aggTrades", params=params, weight=20)
                    break
                except Exception as e:
                    if attempt == retries - 1:
                        raise RuntimeError(f"Failed to fetch trades after {retries} attempts: {e}")
                    await asyncio.sleep(sleep_duration * (attempt + 1))
            else:
                trades = []

            if not trades:
                break

            # === Filter trades if they would exceed total_trades ===
            filtered_trades = []
            temp_count = 0

            for t in trades:
                trade_count = (t['l'] + 1) - t['f']
                if total_trades and (temp_count + trade_count > remaining_needed):
                    break
                filtered_trades.append(t)
                temp_count += trade_count

            trades = filtered_trades
            real_trades_fetched += temp_count
            total_qty_raw += sum([float(t['q']) for t in trades])

            # === Grouping ===
            agg_trade_sum = None

            for raw in trades:
                try:
                    agg = AggTradeModel.model_validate(raw)
                except Exception as e:
                    print(f"Skipping invalid trade: {e}")
                    continue

                if agg_trade_sum is None:
                    agg_trade_sum = AggTradesSum(price=agg.price, first_id=agg.id)

                if agg.price == agg_trade_sum.price:
                    agg_trade_sum.update(agg)
                else:
                    if agg_trade_sum.num_trades > 0:
                        all_trades.append(agg_trade_sum)
                    agg_trade_sum = AggTradesSum(price=agg.price)
                    agg_trade_sum.update(agg)

            if agg_trade_sum and agg_trade_sum.num_trades > 0:
                all_trades.append(agg_trade_sum)

            if real_trades_fetched >= total_trades:
                break
            if not trades:
                break
            if remaining_needed <= 0:
                break

            last_trade_id = trades[-1]['a']
            current_id = last_trade_id + 1
        return all_trades

    async def fetch_historical_klines(
        self,
        symbol: str,
        interval: KlineIntervals = KlineIntervals.m5,
        start_time: Optional[Union[str, int]] = None,
        end_time: Optional[Union[str, int]] = None,
        limit_per_req: int = 1500
    ) -> List[KlineModel]:
        start_ms = to_milliseconds(start_time) if start_time is not None else None
        end_ms = to_milliseconds(end_time, end_of_day=True) - 1 if end_time is not None else None

        all_klines: List[KlineModel] = []
        limit_per_req = min(limit_per_req, 1500)
        curr_start = start_ms

        while True:
            params = {
                "symbol": symbol,
                "interval": interval.value,
                "limit": limit_per_req
            }

            if curr_start is not None:
                params["startTime"] = curr_start
            if end_ms is not None:
                params["endTime"] = end_ms

            weight = (
                1 if limit_per_req <= 100
                else 2 if limit_per_req <= 500
                else 5 if limit_per_req <= 1000
                else 10
            )

            raw_klines = await self._request("GET", "/fapi/v1/klines", params=params, weight=weight)
            if not raw_klines:
                break

            for k in raw_klines:
                kline = KlineModel(
                    open_time=k[0],
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    close_time=k[6],
                    quote_volume=float(k[7]),
                    num_trades=int(k[8]),
                    taker_buy_base_asset_volume=float(k[9]),
                    taker_buy_quote_asset_volume=float(k[10]),
                    recent_trades=[]  # Mặc định không có trade data ở đây
                )
                all_klines.append(kline)

            last_kline_close_time = raw_klines[-1][6]
            next_start_time = last_kline_close_time

            if end_ms is not None and next_start_time > end_ms:
                break

            curr_start = next_start_time

            if len(raw_klines) < limit_per_req:
                break

        return all_klines


    async def get_index_info(self, symbol: str) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v1/indexInfo", params={"symbol": symbol}, weight=1)

    async def close(self):
        await self.session.close()
