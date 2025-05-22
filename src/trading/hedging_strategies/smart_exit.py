import os
import csv
from datetime import datetime

class SmartExitManager:
    def __init__(
        self,
        position: dict,
        ohlcv_m5: dict,
        ohlcv_h1: dict,
        symbol: str,
        config: dict = None,
        log_dir: str = "./logs",
    ):
        self.symbol = symbol
        self.position = position
        self.side = position['side']
        self.entry = position['entry_price']
        self.size = position['size']
        self.open_time = position.get('open_time')

        self.ohlcv_m5 = pd.DataFrame(ohlcv_m5)
        self.ohlcv_h1 = pd.DataFrame(ohlcv_h1)

        self._prepare_indicators()

        # Config mặc định
        default_config = {
            "atr_period": 14,
            "atr_sl_factor": 1.5,
            "atr_trailing_factor": 1.2,
            "breakeven_threshold_atr": 1.5,
            "rsi_period": 14,
            "rsi_exit_long": 75,
            "rsi_exit_short": 25,
            "tp_levels": [1.02, 1.05, 1.1],  # ví dụ tp 2%, 5%, 10%
        }
        self.config = {**default_config, **(config or {})}

        self.max_profit_price = self.entry
        self.has_breakeven = False

        # Setup logging
        os.makedirs(log_dir, exist_ok=True)
        self.log_file_path = os.path.join(log_dir, f"{symbol}_exit_log.csv")
        if not os.path.isfile(self.log_file_path):
            with open(self.log_file_path, mode="w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["timestamp", "symbol", "side", "price", "action", "reason", "size"]
                )

    def _prepare_indicators(self):
        self.ohlcv_h1['atr'] = ta.volatility.AverageTrueRange(
            high=self.ohlcv_h1['high'],
            low=self.ohlcv_h1['low'],
            close=self.ohlcv_h1['close'],
            window=self.config["atr_period"],
        ).average_true_range()

        self.ohlcv_m5['ema21'] = ta.trend.EMAIndicator(
            close=self.ohlcv_m5['close'],
            window=21
        ).ema_indicator()

        self.ohlcv_m5['rsi'] = ta.momentum.RSIIndicator(
            close=self.ohlcv_m5['close'],
            window=self.config["rsi_period"]
        ).rsi()

    def _log(self, reason: str, price: float, action: str, size: Optional[float] = None):
        log_str = f"[{datetime.utcnow()}] EXIT {self.symbol.upper()} - {self.side.upper()} @ {price:.2f} | ACTION: {action} | REASON: {reason}"
        if size:
            log_str += f" | SIZE: {size}"
        logging.info(log_str)

        # Append to CSV
        with open(self.log_file_path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                self.symbol,
                self.side,
                price,
                action,
                reason,
                size or self.size,
            ])

    def evaluate_exit(self, current_price: float) -> Optional[dict]:
        # Update max profit price
        if self.side == 'long' and current_price > self.max_profit_price:
            self.max_profit_price = current_price
        elif self.side == 'short' and current_price < self.max_profit_price:
            self.max_profit_price = current_price

        atr = self.ohlcv_h1['atr'].iloc[-1]
        atr_sl = self.entry - atr * self.config["atr_sl_factor"] if self.side == 'long' else self.entry + atr * self.config["atr_sl_factor"]

        # Trailing stop
        trail_threshold = self.max_profit_price - atr * self.config["atr_trailing_factor"] if self.side == 'long' else self.max_profit_price + atr * self.config["atr_trailing_factor"]
        if (self.side == 'long' and current_price <= trail_threshold) or (self.side == 'short' and current_price >= trail_threshold):
            self._log("Trailing SL", current_price, "exit")
            return {"action": "exit", "reason": "trailing_sl", "price": current_price}

        # Breakeven
        if not self.has_breakeven:
            if (self.side == 'long' and current_price >= self.entry + atr * self.config["breakeven_threshold_atr"]) or \
               (self.side == 'short' and current_price <= self.entry - atr * self.config["breakeven_threshold_atr"]):
                self.has_breakeven = True
                self._log("Move SL to breakeven", self.entry, "adjust_sl")
                return {"action": "adjust_sl", "new_sl": self.entry, "reason": "breakeven"}

        # RSI exit
        rsi = self.ohlcv_m5['rsi'].iloc[-1]
        if (self.side == 'long' and rsi > self.config["rsi_exit_long"]) or (self.side == 'short' and rsi < self.config["rsi_exit_short"]):
            self._log("RSI exit", current_price, "exit")
            return {"action": "exit", "reason": "rsi_extreme", "price": current_price}

        return None


import random
from time import sleep

class PriceSimulator:
    def __init__(self, start_price: float, volatility: float = 0.005):
        self.price = start_price
        self.volatility = volatility

    def next_price(self) -> float:
        # Mô phỏng giá đi lên hoặc xuống theo volatility (tỉ lệ %)
        move_pct = random.uniform(-self.volatility, self.volatility)
        self.price *= (1 + move_pct)
        return round(self.price, 2)


def run_simulation(manager, steps=100):
    print(f"Start simulation for {manager.symbol} {manager.side} position")
    simulator = PriceSimulator(manager.entry)

    for i in range(steps):
        price = simulator.next_price()

        result = manager.evaluate_exit(price)
        if result:
            action = result.get("action")
            reason = result.get("reason")
            print(f"Step {i+1}: Price={price} => {action} due to {reason}")
            if action == "exit":
                print(f"Position closed at price {price}")
                break
            elif action == "adjust_sl":
                print(f"Stoploss adjusted to {result['new_sl']}")
        else:
            print(f"Step {i+1}: Price={price} => Hold")

        sleep(0.05)  # delay giả lập realtime (bạn có thể bỏ)
