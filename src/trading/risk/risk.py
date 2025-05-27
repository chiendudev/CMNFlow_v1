# risk_manager.py - Risk Manager Optimized for Scalping Strategies

from typing import Dict, List
from decimal import Decimal, ROUND_DOWN
import logging
import math

logger = logging.getLogger(__name__)

class RiskEvent:
    def __init__(self, message: str, level: str = 'WARNING'):
        self.message = message
        self.level = level

class RiskManager:
    def __init__(self, settings, portfolio, market_data, notifier=None):
        self.settings = settings
        self.portfolio = portfolio
        self.market_data = market_data
        self.notifier = notifier  # Optional integration for Discord/Telegram

    def check_risk(self, symbol: str, side: str, signal: Dict) -> List[RiskEvent]:
        events = []

        if not self._check_dynamic_leverage(symbol):
            events.append(RiskEvent(f"Dynamic leverage too high for {symbol}", 'ERROR'))

        if self._is_drawdown_exceeded():
            events.append(RiskEvent("Max drawdown exceeded. Trading halted.", 'CRITICAL'))

        if self._is_position_size_too_large(symbol, signal):
            events.append(RiskEvent(f"Position size too large for {symbol}", 'WARNING'))

        if self._is_price_spike(symbol):
            events.append(RiskEvent(f"Price spike detected on {symbol}. Delay entry.", 'WARNING'))

        if self._is_too_many_positions():
            events.append(RiskEvent("Too many concurrent positions open", 'WARNING'))

        if self._is_unusual_volume(symbol):
            events.append(RiskEvent(f"Unusual volume spike on {symbol}. Caution advised.", 'WARNING'))

        if self._is_liquidity_risk_high(symbol):
            events.append(RiskEvent(f"Liquidity risk detected for {symbol}. Slippage expected.", 'WARNING'))

        if self._is_spread_too_wide(symbol):
            events.append(RiskEvent(f"Order book spread too wide for {symbol}. Entry risk too high.", 'WARNING'))

        if self._is_near_funding(symbol):
            events.append(RiskEvent(f"{symbol} is near funding time. Avoid entering now.", 'WARNING'))

        if self._is_in_cooldown():
            events.append(RiskEvent("System in cooldown mode due to recent drawdowns.", 'CRITICAL'))

        self._log_and_notify(events)
        return events

    def _check_dynamic_leverage(self, symbol: str) -> bool:
        volatility = self.market_data.get_volatility(symbol)
        base_leverage = self.settings.leverage
        reduction_factor = 1.0

        if volatility > self.settings.volatility_threshold:
            reduction_factor *= 0.7

        effective_leverage = base_leverage * reduction_factor
        max_leverage = self.market_data.get_max_leverage(symbol)
        return effective_leverage <= max_leverage

    def _is_drawdown_exceeded(self) -> bool:
        drawdown = self.portfolio.get_drawdown()
        return drawdown > self.settings.max_drawdown

    def _is_position_size_too_large(self, symbol: str, signal: Dict) -> bool:
        size = signal.get("size")
        balance = self.portfolio.get_balance()
        max_size = balance * self.settings.max_risk_per_trade
        return size > max_size

    def _is_price_spike(self, symbol: str) -> bool:
        return self.market_data.detect_spike(symbol)

    def _is_too_many_positions(self) -> bool:
        return self.portfolio.active_positions_count() >= self.settings.max_concurrent_positions

    def _is_unusual_volume(self, symbol: str) -> bool:
        volume = self.market_data.get_current_volume(symbol)
        avg_volume = self.market_data.get_average_volume(symbol)
        return volume > avg_volume * self.settings.volume_spike_threshold

    def _is_liquidity_risk_high(self, symbol: str) -> bool:
        slippage = self.market_data.estimate_slippage(symbol)
        return slippage > self.settings.max_slippage_threshold

    def _is_spread_too_wide(self, symbol: str) -> bool:
        spread = self.market_data.get_orderbook_spread(symbol)
        return spread > self.settings.max_spread_threshold

    def _is_near_funding(self, symbol: str) -> bool:
        seconds_to_funding = self.market_data.get_seconds_to_next_funding(symbol)
        return seconds_to_funding < self.settings.min_seconds_to_funding

    def _is_in_cooldown(self) -> bool:
        return self.portfolio.is_in_cooldown_mode()

    def get_adjusted_position_size(self, symbol: str, price: float, atr: float) -> float:
        balance = self.portfolio.get_balance()
        risk_per_trade = self.settings.max_risk_per_trade
        sl_distance = max(atr * self.settings.atr_multiplier, self.market_data.get_min_sl_distance(symbol))
        dollar_risk = balance * risk_per_trade
        size = dollar_risk / sl_distance
        return self._round_lot_size(symbol, size)

    def _round_lot_size(self, symbol: str, size: float) -> float:
        step_size = self.market_data.get_step_size(symbol)
        d_size = Decimal(size)
        d_step = Decimal(str(step_size))
        rounded = (d_size // d_step) * d_step
        return float(rounded.quantize(d_step, rounding=ROUND_DOWN))

    def evaluate_exit_strategy(self, symbol: str, price: float, atr: float) -> Dict[str, float]:
        sl = price - atr * self.settings.sl_atr_factor
        tp = price + atr * self.settings.tp_atr_factor
        return {"stop_loss": sl, "take_profit": tp}

    def _log_and_notify(self, events: List[RiskEvent]):
        for event in events:
            if event.level == 'CRITICAL':
                logger.critical(event.message)
            elif event.level == 'ERROR':
                logger.error(event.message)
            elif event.level == 'WARNING':
                logger.warning(event.message)
            else:
                logger.info(event.message)
            if self.notifier:
                self.notifier.send(event.message, level=event.level)

    def backtest_check_risk(self, symbol: str, side: str, signal: Dict, historical_portfolio, historical_market_data) -> List[RiskEvent]:
        original_portfolio = self.portfolio
        original_market_data = self.market_data

        self.portfolio = historical_portfolio
        self.market_data = historical_market_data
        events = self.check_risk(symbol, side, signal)

        self.portfolio = original_portfolio
        self.market_data = original_market_data
        return events

    def filter_blocking_events(self, events: List[RiskEvent]) -> List[RiskEvent]:
        return [event for event in events if event.level in ('CRITICAL', 'ERROR')]

    def filter_warning_events(self, events: List[RiskEvent]) -> List[RiskEvent]:
        return [event for event in events if event.level == 'WARNING']

    def filter_nonblocking_events(self, events: List[RiskEvent]) -> List[RiskEvent]:
        return [event for event in events if event.level not in ('CRITICAL', 'ERROR')]

    def has_blocking_event(self, events: List[RiskEvent]) -> bool:
        return any(event.level in ('CRITICAL', 'ERROR') for event in events)
