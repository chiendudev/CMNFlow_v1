from typing import List, Dict, Optional
from old.config.settings import Settings
import logging
import time
import math

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self, technical, settings: Settings):
        self.technical = technical
        self.settings = settings
        self.stop_hunt_events: List[Dict] = []

    def detect_stop_hunt(self, timeframe: str, sensitive_prices: List[float]) -> Optional[Dict]:
        kline = self.technical.kline
        if not kline.recent_trades:
            return None
        volumes = [t["quantity"] for t in kline.recent_trades]
        mean_vol = sum(volumes) / len(volumes) if volumes else 0.0
        std_vol = math.sqrt(sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)) if len(volumes) > 1 else 0.0
        taker_qty = sum(t["quantity"] for t in kline.recent_trades if not t["is_maker"])
        total_qty = sum(t["quantity"] for t in kline.recent_trades)
        taker_ratio = taker_qty / total_qty if total_qty > 0 else 0.0
        min_price = min(t["price"] for t in kline.recent_trades)
        max_price = max(t["price"] for t in kline.recent_trades)
        price_move = (max_price - min_price) / min_price
        stop_hunt_detected = False
        target_price = None
        direction = None
        atr_factor = 2.0 if self.technical.atr else 1.0
        if (price_move >= self.settings.stop_hunt_price_move * atr_factor and
            taker_ratio >= self.settings.stop_hunt_taker_ratio and
            (self.technical.rsi is None or self.technical.rsi < self.settings.rsi_oversold or self.technical.rsi > self.settings.rsi_overbought)):
            spike_volumes = [t["quantity"] for t in kline.recent_trades if t["quantity"] > mean_vol + self.settings.stop_hunt_volume_spike * std_vol]
            if spike_volumes:
                for price in sensitive_prices:
                    if any(abs(t["price"] - price) <= price * self.settings.price_range_pct for t in kline.recent_trades):
                        last_trades = sorted(kline.recent_trades, key=lambda x: x["timestamp_ms"], reverse=True)[:5]
                        last_price = last_trades[0]["price"] if last_trades else kline.close
                        if abs(last_price - min_price) >= min_price * self.settings.stop_hunt_reversal and last_price > min_price:
                            direction = "down"
                            target_price = min_price
                            stop_hunt_detected = True
                        elif abs(last_price - max_price) >= max_price * self.settings.stop_hunt_reversal and last_price < max_price:
                            direction = "up"
                            target_price = max_price
                            stop_hunt_detected = True
                        break
        if stop_hunt_detected:
            event = {
                "symbol": kline.symbol,
                "timeframe": timeframe,
                "timestamp_ms": kline.recent_trades[-1]["timestamp_ms"],
                "target_price": round(target_price, self.settings.price_precision),
                "direction": direction,
                "volume": sum(t["quantity"] for t in kline.recent_trades),
                "taker_ratio": taker_ratio,
                "price_move": price_move,
                "technical_indicators": {
                    "rsi": self.technical.rsi,
                    "atr": self.technical.atr,
                    "ema_fast": self.technical.ema_fast,
                    "ema_slow": self.technical.ema_slow
                }
            }
            self.stop_hunt_events.append(event)
            return event
        return None

    def generate(self, timeframe: str, confluence_zones: List[Dict]) -> List[Dict]:
        kline = self.technical.kline
        signals = []
        zones, _, _, poc_price, value_area = self.technical.analyze_zones(timeframe)
        sensitive_prices = []
        for zone in zones + confluence_zones:
            sensitive_prices.append(zone["center_price"])
            sensitive_prices.extend(zone["price_range"] if "price_range" in zone else [])
        min_price = min(kline.price_qty.keys(), default=kline.close)
        max_price = max(kline.price_qty.keys(), default=kline.close)
        sensitive_prices.extend([round(p, 0) for p in range(int(min_price // 100 * 100), int(max_price // 100 * 100) + 100, 100)])
        stop_hunt = self.detect_stop_hunt(timeframe, sensitive_prices)
        stop_hunt_risk = 0.0
        if stop_hunt:
            stop_hunt_risk = min(1.0, stop_hunt["price_move"] / self.settings.stop_hunt_price_move + stop_hunt["taker_ratio"])
        current_time = time.time()
        recent_stop_hunts = [e for e in self.stop_hunt_events if current_time - e["timestamp_ms"] / 1000 <= self.settings.stop_hunt_risk_window]
        risky_prices = [e["target_price"] for e in recent_stop_hunts]
        trend = "bullish" if self.technical.ema_fast and self.technical.ema_slow and self.technical.ema_fast > self.technical.ema_slow else \
                "bearish" if self.technical.ema_fast and self.technical.ema_slow and self.technical.ema_fast < self.technical.ema_slow else \
                "neutral"
        for zone in zones + confluence_zones:
            is_confluence = zone in confluence_zones
            center_price = zone["center_price"]
            zone_type = zone["type"]
            reliability = zone["reliability"]
            breakout_prob = zone["breakout_probability"] if "breakout_probability" in zone else 0.0
            maker_ratio = zone["maker_ratio"]
            price_range = zone["price_range"] if "price_range" in zone else [center_price, center_price]
            if reliability < self.settings.min_reliability or breakout_prob > self.settings.max_breakout_prob:
                continue
            if any(abs(center_price - rp) <= center_price * self.settings.price_range_pct for rp in risky_prices):
                continue
            rsi_condition = self.technical.rsi is None or \
                           (zone_type == "support" and self.technical.rsi < self.settings.rsi_overbought) or \
                           (zone_type == "resistance" and self.technical.rsi > self.settings.rsi_oversold)
            ema_condition = self.technical.ema_fast is None or self.technical.ema_slow is None or \
                           (zone_type == "support" and trend == "bullish") or \
                           (zone_type == "resistance" and trend == "bearish") or \
                           trend == "neutral"
            if not (rsi_condition and ema_condition):
                continue
            if abs(kline.close - center_price) <= center_price * self.settings.price_range_pct:
                if zone_type == "support" and (trend == "bullish" or trend == "neutral"):
                    entry = center_price
                    stop_loss = min(price_range) - (self.technical.atr * self.settings.atr_stop_loss_factor if self.technical.atr else min(price_range) * self.settings.stop_loss_buffer)
                    for rp in sensitive_prices + risky_prices:
                        if abs(stop_loss - rp) <= rp * self.settings.price_range_pct:
                            stop_loss -= self.technical.atr * self.settings.atr_stop_loss_factor if self.technical.atr else min(price_range) * self.settings.stop_loss_buffer
                            break
                    resistance = None
                    for z in zones:
                        if z["type"] == "resistance" and z["center_price"] > entry:
                            if not resistance or z["center_price"] < resistance["center_price"]:
                                resistance = z
                    take_profit = resistance["center_price"] if resistance else \
                                  entry + (self.technical.atr * self.settings.atr_take_profit_factor if self.technical.atr else entry * 0.02)
                    risk = entry - stop_loss
                    reward = take_profit - entry
                    if reward / risk >= self.settings.risk_reward_ratio:
                        reason = f"Price near {'confluence ' if is_confluence else ''}support zone at {center_price}, " \
                                 f"MakerRatio={maker_ratio:.2f}, Reliability={reliability:.2f}, " \
                                 f"RSI={self.technical.rsi:.1f}, Trend={'Bullish' if trend == 'bullish' else 'Bearish' if trend == 'bearish' else 'Neutral'}"
                        signals.append({
                            "symbol": kline.symbol,
                            "type": "buy",
                            "entry": round(entry, self.settings.price_precision),
                            "stop_loss": round(stop_loss, self.settings.price_precision),
                            "take_profit": round(take_profit, self.settings.price_precision),
                            "risk_reward_ratio": round(reward / risk, 2),
                            "reason": reason,
                            "timeframe": timeframe if not is_confluence else "confluence",
                            "reliability": reliability,
                            "stop_hunt_risk": stop_hunt_risk,
                            "technical_indicators": {
                                "rsi": self.technical.rsi,
                                "atr": self.technical.atr,
                                "ema_fast": self.technical.ema_fast,
                                "ema_slow": self.technical.ema_slow
                            }
                        })
                elif zone_type == "resistance" and (trend == "bearish" or trend == "neutral"):
                    entry = center_price
                    stop_loss = max(price_range) + (self.technical.atr * self.settings.atr_stop_loss_factor if self.technical.atr else max(price_range) * self.settings.stop_loss_buffer)
                    for rp in sensitive_prices + risky_prices:
                        if abs(stop_loss - rp) <= rp * self.settings.price_range_pct:
                            stop_loss += self.technical.atr * self.settings.atr_stop_loss_factor if self.technical.atr else max(price_range) * self.settings.stop_loss_buffer
                            break
                    support = None
                    for z in zones:
                        if z["type"] == "support" and z["center_price"] < entry:
                            if not support or z["center_price"] > support["center_price"]:
                                support = z
                    take_profit = support["center_price"] if support else \
                                  entry - (self.technical.atr * self.settings.atr_take_profit_factor if self.technical.atr else entry * 0.02)
                    risk = stop_loss - entry
                    reward = entry - take_profit
                    if reward / risk >= self.settings.risk_reward_ratio:
                        reason = f"Price near {'confluence ' if is_confluence else ''}resistance zone at {center_price}, " \
                                 f"MakerRatio={maker_ratio:.2f}, Reliability={reliability:.2f}, " \
                                 f"RSI={self.technical.rsi:.1f}, Trend={'Bullish' if trend == 'bullish' else 'Bearish' if trend == 'bearish' else 'Neutral'}"
                        signals.append({
                            "symbol": kline.symbol,
                            "type": "sell",
                            "entry": round(entry, self.settings.price_precision),
                            "stop_loss": round(stop_loss, self.settings.price_precision),
                            "take_profit": round(take_profit, self.settings.price_precision),
                            "risk_reward_ratio": round(reward / risk, 2),
                            "reason": reason,
                            "timeframe": timeframe if not is_confluence else "confluence",
                            "reliability": reliability,
                            "stop_hunt_risk": stop_hunt_risk,
                            "technical_indicators": {
                                "rsi": self.technical.rsi,
                                "atr": self.technical.atr,
                                "ema_fast": self.technical.ema_fast,
                                "ema_slow": self.technical.ema_slow
                            }
                        })
        return signals