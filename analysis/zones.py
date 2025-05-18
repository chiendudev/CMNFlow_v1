from typing import List, Dict, Tuple, Optional
from config.settings import Settings
import logging
import math

logger = logging.getLogger(__name__)

class ZoneAnalyzer:
    def __init__(self, technical, settings: Settings):
        self.technical = technical
        self.settings = settings

    def analyze(self, timeframe: str) -> Tuple[List[Dict], Dict, Dict, Optional[float], Optional[List[float]]]:
        kline = self.technical.kline
        if not kline.price_qty:
            return [], {}, {}, None, None
        volumes = [data["maker_qty"] + data["taker_qty"] for data in kline.price_qty.values()]
        mean_vol = sum(volumes) / len(volumes) if volumes else 0.0
        std_vol = math.sqrt(sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)) if len(volumes) > 1 else 0.0
        price_bins = {}
        min_price = min(kline.price_qty.keys())
        max_price = max(kline.price_qty.keys())
        bin_size = (max_price - min_price) / 20 if max_price > min_price else 0.01
        for price in kline.price_qty:
            bin_price = round(min_price + ((price - min_price) // bin_size) * bin_size, self.settings.price_precision)
            if bin_price not in price_bins:
                price_bins[bin_price] = {"total_qty": 0.0, "trades": 0}
            price_bins[bin_price]["total_qty"] += kline.price_qty[price]["maker_qty"] + kline.price_qty[price]["taker_qty"]
            price_bins[bin_price]["trades"] += kline.price_qty[price]["count"]
        poc = max(price_bins.items(), key=lambda x: x[1]["total_qty"]) if price_bins else (None, {"total_qty": 0, "trades": 0})
        poc_price, poc_data = poc
        sorted_bins = sorted(price_bins.items(), key=lambda x: x[1]["total_qty"], reverse=True)
        total_volume = sum(v["total_qty"] for _, v in sorted_bins)
        value_area_volume = 0.0
        value_area_prices = []
        for price, data in sorted_bins:
            value_area_volume += data["total_qty"]
            value_area_prices.append(price)
            if value_area_volume >= total_volume * self.settings.value_area_pct:
                break
        value_area = [min(value_area_prices), max(value_area_prices)] if value_area_prices else [min_price, max_price]
        price_zones = []
        sorted_prices = sorted(kline.price_qty.keys())
        current_zone = None
        for price in sorted_prices:
            data = kline.price_qty[price]
            total_qty = data["maker_qty"] + data["taker_qty"]
            count = data["count"]
            if current_zone and abs(price - current_zone["center_price"]) <= current_zone["center_price"] * self.settings.price_range_pct:
                current_zone["prices"].append(price)
                current_zone["total_qty"] += total_qty
                current_zone["maker_qty"] += data["maker_qty"]
                current_zone["taker_qty"] += data["taker_qty"]
                current_zone["trades"] += count
                current_zone["center_price"] = (min(current_zone["prices"]) + max(current_zone["prices"])) / 2
            else:
                if current_zone:
                    price_zones.append(current_zone)
                current_zone = {
                    "center_price": price,
                    "prices": [price],
                    "total_qty": total_qty,
                    "maker_qty": data["maker_qty"],
                    "taker_qty": data["taker_qty"],
                    "trades": count
                }
        if current_zone:
            price_zones.append(current_zone)
        significant_zones = []
        avg_qty_per_price = {}
        trend = "bullish" if kline.close > kline.open else "bearish" if kline.close < kline.open else "neutral"
        if self.technical.ema_fast and self.technical.ema_slow:
            trend = "bullish" if self.technical.ema_fast > self.technical.ema_slow else "bearish" if self.technical.ema_fast < self.technical.ema_slow else trend
        for zone in price_zones:
            total_qty = zone["total_qty"]
            trades = zone["trades"]
            maker_ratio = zone["maker_qty"] / total_qty if total_qty > 0 else 0.0
            maker_avg = zone["maker_qty"] / trades if zone["maker_qty"] > 0 else 0.0
            taker_avg = zone["taker_qty"] / trades if zone["taker_qty"] > 0 else 0.0
            for price in zone["prices"]:
                avg_qty_per_price[price] = {"maker_avg_qty": maker_avg, "taker_avg_qty": taker_avg}
            is_significant = (
                total_qty > mean_vol + self.settings.volume_threshold * std_vol or
                total_qty > kline.volume * self.settings.volume_percent
            ) and trades >= self.settings.min_trades
            if is_significant:
                zone_type = "unknown"
                if maker_ratio > 0.7:
                    if zone["center_price"] < kline.close:
                        zone_type = "support" if self.technical.rsi is None or self.technical.rsi < self.settings.rsi_overbought else "unknown"
                    else:
                        zone_type = "resistance" if self.technical.rsi is None or self.technical.rsi > self.settings.rsi_oversold else "unknown"
                elif maker_ratio < 0.3:
                    zone_type = "breakout"
                price_range = max(zone["prices"]) - min(zone["prices"])
                depth = total_qty / price_range if price_range > 0 else total_qty
                breakout_prob = 0.0
                if maker_ratio < 0.3 and total_qty > mean_vol + 3 * std_vol:
                    breakout_prob = min(1.0, 0.5 + (1 - maker_ratio) * 0.5)
                    if trend == "bullish" and zone["center_price"] > kline.close:
                        breakout_prob += 0.2
                    elif trend == "bearish" and zone["center_price"] < kline.close:
                        breakout_prob += 0.2
                timeframe_weight = {"1m": 0.5, "5m": 0.75, "15m": 1.0}.get(timeframe, 0.5)
                reliability = min(1.0, (trades / 50) + (total_qty / kline.volume) * 2 + timeframe_weight)
                if self.technical.rsi and zone_type == "support" and self.technical.rsi < self.settings.rsi_oversold:
                    reliability += 0.1
                elif self.technical.rsi and zone_type == "resistance" and self.technical.rsi > self.settings.rsi_overbought:
                    reliability += 0.1
                if self.technical.ema_fast and self.technical.ema_slow and zone_type == "support" and self.technical.ema_fast > self.technical.ema_slow:
                    reliability += 0.1
                elif self.technical.ema_fast and self.technical.ema_slow and zone_type == "resistance" and self.technical.ema_fast < self.technical.ema_slow:
                    reliability += 0.1
                significant_zones.append({
                    "center_price": round(zone["center_price"], self.settings.price_precision),
                    "price_range": [min(zone["prices"]), max(zone["prices"])],
                    "total_volume": total_qty,
                    "trades": trades,
                    "maker_ratio": maker_ratio,
                    "type": zone_type,
                    "depth": depth,
                    "breakout_probability": breakout_prob,
                    "reliability": reliability
                })
        return significant_zones, avg_qty_per_price, price_bins, poc_price, value_area