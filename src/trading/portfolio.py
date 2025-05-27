from typing import Dict, Optional, List, Any
from functools import lru_cache
import logging
from src.trading.position import Position
from src.trading.enums import PositionSide, OrderSide, OrderType
from src.trading.orders import Order
from src.utils.symbol_info import SymbolInfo
from src.trading.risk.risk import RiskManager
#from src.trading.trend_analyzer import TrendAnalyzer
from src.Account.account_info import AccountInfo, OpenPosition, FutureBalance

logger = logging.getLogger(__name__)

class Portfolio:
    def __init__(
        self,
        account_info: Optional[AccountInfo] = None,
        hedge_mode: bool = False,
        symbol_info_map: Optional[Dict[str, SymbolInfo]] = None,
        risk_manager: Optional[RiskManager] = None,
        #trend_analyzer: Optional[TrendAnalyzer] = None,
    ):
        """
        Khởi tạo danh mục đầu tư cho Binance Futures, tích hợp với AccountInfo.

        Args:
            account_info: Đối tượng AccountInfo để lấy dữ liệu tài khoản.
            hedge_mode: True nếu sử dụng chế độ Hedge Mode.
            symbol_info_map: Từ điển ánh xạ symbol tới SymbolInfo.
            risk_manager: Đối tượng RiskManager để kiểm tra rủi ro.
            trend_analyzer: Đối tượng TrendAnalyzer để phân tích xu hướng.
        """
        self.account_info = account_info
        self.hedge_mode = hedge_mode
        self.positions: Dict[str, Dict[PositionSide, Position]] = {}
        self.symbol_info_map = symbol_info_map or {}
        self.risk_manager = risk_manager
        #self.trend_analyzer = trend_analyzer
        self._cache = {}  # Cache cho các chỉ số danh mục

        # Khởi tạo từ AccountInfo nếu có
        if self.account_info:
            self._sync_from_account_info()

    async def initialize(self):
        """
        Khởi tạo danh mục từ dữ liệu AccountInfo.
        """
        try:
            if self.account_info:
                await self.account_info.initial()
                self._sync_from_account_info()
        except Exception as e:
            logger.error(f"Lỗi khi khởi tạo danh mục: {str(e)}")
            raise

    def _sync_from_account_info(self):
        """
        Đồng bộ danh mục với dữ liệu từ AccountInfo.
        """
        try:
            if not self.account_info:
                return

            # Cập nhật số dư ví
            self.wallet_balance = self.account_info.available_balance

            # Cập nhật vị thế
            self.positions.clear()
            for pos in self.account_info.open_positions:
                symbol = pos.symbol
                side = PositionSide[pos.position_side] if self.hedge_mode else PositionSide.BOTH
                symbol_info = self._get_symbol_info(symbol)
                if not symbol_info:
                    logger.warning(f"SymbolInfo không tồn tại cho {symbol}")
                    continue

                if symbol not in self.positions:
                    self.positions[symbol] = {}
                if side not in self.positions[symbol]:
                    self.positions[symbol][side] = Position(
                        symbol_info=symbol_info,
                        symbol=symbol,
                        position_side=side,
                        position_amt=pos.position_amt,
                        unrealized_profit=pos.unrealized_profit,
                        isolated_margin=pos.isolated_margin,
                        notional=pos.notional,
                        isolated_wallet=pos.isolated_wallet,
                        initial_margin=pos.initial_margin,
                        maint_margin=pos.maint_margin,
                        update_time=int(pos.update_time),
                    )
            self._cache.clear()  # Xóa cache khi đồng bộ
        except Exception as e:
            logger.error(f"Lỗi khi đồng bộ từ AccountInfo: {str(e)}")

    def apply_order(self, order: Order):
        """
        Áp dụng lệnh mới vào danh mục.

        Args:
            order: Lệnh giao dịch.

        Raises:
            ValueError: Nếu số dư không đủ hoặc lệnh không hợp lệ.
        """
        try:
            symbol = order.symbol
            side = order.position_side if self.hedge_mode else PositionSide.BOTH

            # Kiểm tra SymbolInfo
            symbol_info = self._get_symbol_info(symbol)
            if not symbol_info:
                raise ValueError(f"SymbolInfo không tồn tại cho {symbol}")

            # Kiểm tra xu hướng với TrendAnalyzer
            if self.trend_analyzer:
                trend_data = self.trend_analyzer.for_risk_manager(symbol, "15m")
                if not trend_data["is_trending"]:
                    logger.warning(f"Không áp dụng lệnh do xu hướng yếu cho {symbol}")
                    return

            # Tính phí
            is_maker = order.type == OrderType.LIMIT
            order.calculate_fee(
                is_maker=is_maker,
                maker_fee=symbol_info.maker_commission_rate,
                taker_fee=symbol_info.taker_commission_rate,
            )

            # Kiểm tra rủi ro với RiskManager
            if self.risk_manager:
                signal = {"size": order.quantity * order.price}
                risk_events = self.risk_manager.check_risk(symbol, order.side.name, signal)
                if any(event.level in ['ERROR', 'CRITICAL'] for event in risk_events):
                    raise ValueError(f"Rủi ro cao: {', '.join(e.message for e in risk_events)}")

            # Tính initial_margin
            pos = self.get_position(symbol, side)
            temp_notional = abs(
                pos.position_amt + (order.quantity if order.side == OrderSide.BUY else -order.quantity)
            ) * order.price
            initial_margin = temp_notional / symbol_info.leverage

            # Kiểm tra số dư từ AccountInfo
            available_balance = self.account_info.available_balance if self.account_info else self.wallet_balance
            if available_balance < initial_margin + order.fee:
                raise ValueError(
                    f"Số dư không đủ ({available_balance}) cho initial_margin ({initial_margin}) và phí ({order.fee})"
                )

            # Cập nhật lệnh
            self.update_order(symbol, order, side)
            self.wallet_balance -= order.fee
            realized = pos.realized_profit
            self.wallet_balance += realized
            pos.realized_profit = 0.0
            self._cache.clear()

            # Cập nhật AccountInfo nếu có
            if self.account_info:
                self.account_info.available_balance = self.wallet_balance
        except Exception as e:
            logger.error(f"Lỗi khi áp dụng lệnh cho {order.symbol}: {str(e)}")
            raise

    @lru_cache(maxsize=128)
    def get_position(self, symbol: str, side: PositionSide = PositionSide.BOTH) -> Position:
        """
        Lấy hoặc khởi tạo vị thế.

        Args:
            symbol: Cặp giao dịch.
            side: Loại vị thế (LONG, SHORT, hoặc BOTH).

        Returns:
            Đối tượng Position.
        """
        try:
            symbol_info = self._get_symbol_info(symbol)
            if not symbol_info:
                raise ValueError(f"SymbolInfo không tồn tại cho {symbol}")

            if symbol not in self.positions:
                self.positions[symbol] = {}
            if side not in self.positions[symbol]:
                self.positions[symbol][side] = Position(
                    symbol_info=symbol_info,
                    symbol=symbol,
                    position_side=side,
                )
            return self.positions[symbol][side]
        except Exception as e:
            logger.error(f"Lỗi khi lấy vị thế {symbol} {side.name}: {str(e)}")
            raise

    def update_order(self, symbol: str, order: Order, side: PositionSide):
        """
        Cập nhật danh mục khi có lệnh mới.

        Args:
            symbol: Cặp giao dịch.
            order: Lệnh giao dịch.
            side: Loại vị thế.
        """
        try:
            symbol_info = self._get_symbol_info(symbol)
            pos = self.get_position(symbol, side)
            pos.update_order_metrics(
                order=order,
                wallet_balance=self.wallet_balance,
            )
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật lệnh cho {symbol}: {str(e)}")
            raise

    def update_mark_price(self, symbol: str, price: float):
        """
        Cập nhật giá thị trường cho các vị thế.

        Args:
            symbol: Cặp giao dịch.
            price: Giá thị trường mới.
        """
        try:
            if symbol not in self.positions:
                return

            symbol_info = self._get_symbol_info(symbol)
            for side, pos in self.positions[symbol].items():
                pos.update_price_metrics(
                    mark_price=price,
                    wallet_balance=self.wallet_balance,
                )
            self._cache.clear()
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật giá thị trường cho {symbol}: {str(e)}")

    def ws_update(self, data: Dict[str, Any]):
        """
        Cập nhật danh mục từ dữ liệu WebSocket.

        Args:
            data: Dữ liệu từ Binance Futures WebSocket.
        """
        try:
            symbol = data.get('s')
            side = PositionSide[data.get('ps', 'BOTH')]
            if symbol not in self.symbol_info_map:
                raise ValueError(f"SymbolInfo không tồn tại cho {symbol}")

            pos = self.get_position(symbol, side)
            pos.ws_update(data)
            self.wallet_balance = float(data.get('wb', self.wallet_balance))
            if self.account_info:
                self.account_info.available_balance = self.wallet_balance
                self.account_info.total_unrealized_profit = self.get_total_unrealized_pnl()
            self._cache.clear()
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật WebSocket cho {symbol}: {str(e)}")

    def get_total_unrealized_pnl(self) -> float:
        """
        Tính tổng lợi nhuận chưa thực hiện.

        Returns:
            Tổng unrealized PNL.
        """
        try:
            if 'total_unrealized_pnl' in self._cache:
                return self._cache['total_unrealized_pnl']
            total = self.account_info.total_unrealized_profit if self.account_info else sum(
                pos.unrealized_profit
                for symbol_pos in self.positions.values()
                for pos in symbol_pos.values()
            )
            self._cache['total_unrealized_pnl'] = total
            return total
        except Exception as e:
            logger.error(f"Lỗi khi tính tổng unrealized PNL: {str(e)}")
            return 0.0

    def get_total_maintenance_margin(self) -> float:
        """
        Tính tổng margin duy trì.

        Returns:
            Tổng maintenance margin.
        """
        try:
            if 'total_maintenance_margin' in self._cache:
                return self._cache['total_maintenance_margin']
            total = self.account_info.total_maint_margin if self.account_info else sum(
                pos.maint_margin
                for symbol_pos in self.positions.values()
                for pos in symbol_pos.values()
            )
            self._cache['total_maintenance_margin'] = total
            return total
        except Exception as e:
            logger.error(f"Lỗi khi tính tổng maintenance margin: {str(e)}")
            return 0.0

    def get_total_position_margin(self) -> float:
        """
        Tính tổng margin yêu cầu cho các vị thế.

        Returns:
            Tổng position margin.
        """
        try:
            if 'total_position_margin' in self._cache:
                return self._cache['total_position_margin']
            total = self.account_info.total_position_initial_margin if self.account_info else sum(
                pos.position_initial_margin
                for symbol_pos in self.positions.values()
                for pos in symbol_pos.values()
            )
            self._cache['total_position_margin'] = total
            return total
        except Exception as e:
            logger.error(f"Lỗi khi tính tổng position margin: {str(e)}")
            return 0.0

    def get_liquidation_risk_symbols(self) -> Dict[str, Dict[PositionSide, float]]:
        """
        Lọc các symbol có nguy cơ thanh lý.

        Returns:
            Từ điển các symbol và giá thanh lý.
        """
        try:
            risk = {}
            for symbol, side_dict in self.positions.items():
                for side, pos in side_dict.items():
                    if pos.position_amt != 0:
                        price_diff = abs(pos.mark_price - pos.liquidation_price) / pos.mark_price
                        if price_diff < 0.05:  # Giá thị trường gần giá thanh lý (<5%)
                            risk.setdefault(symbol, {})[side] = pos.liquidation_price
            return risk
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra rủi ro thanh lý: {str(e)}")
            return {}

    def summary(self) -> Dict[str, Dict[str, Dict]]:
        """
        Tổng hợp dữ liệu danh mục.

        Returns:
            Từ điển tổng hợp theo symbol và position_side.
        """
        try:
            result = {
                "account_info": {
                    "total_wallet_balance": self.account_info.total_wallet_balance if self.account_info else self.wallet_balance,
                    "total_unrealized_profit": self.get_total_unrealized_pnl(),
                    "total_maint_margin": self.get_total_maintenance_margin(),
                    "total_position_margin": self.get_total_position_margin(),
                    "available_balance": self.account_info.available_balance if self.account_info else self.wallet_balance,
                },
                "positions": {}
            }
            for symbol, side_dict in self.positions.items():
                result["positions"][symbol] = {}
                for side, pos in side_dict.items():
                    key = side.name
                    result["positions"][symbol][key] = {
                        "position_amt": pos.position_amt,
                        "entry_price": pos.entry_price,
                        "break_even_price": pos.break_even_price,
                        "unrealized_pnl": pos.unrealized_profit,
                        "liquidation_price": pos.liquidation_price,
                        "notional": pos.notional,
                        "initial_margin": pos.initial_margin,
                        "maint_margin": pos.maint_margin,
                    }
            return result
        except Exception as e:
            logger.error(f"Lỗi khi tổng hợp danh mục: {str(e)}")
            return {}

    def _get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """
        Lấy SymbolInfo cho symbol.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Đối tượng SymbolInfo hoặc None.
        """
        try:
            return self.symbol_info_map.get(symbol)
        except Exception as e:
            logger.error(f"Lỗi khi lấy SymbolInfo cho {symbol}: {str(e)}")
            return None

    def get_drawdown(self) -> float:
        """
        Tính tỷ lệ drawdown của danh mục.

        Returns:
            Tỷ lệ drawdown (%).
        """
        try:
            initial_balance = self.account_info.total_wallet_balance if self.account_info else (
                self.wallet_balance + self.get_total_unrealized_pnl() + self.get_total_position_margin()
            )
            current_balance = self.account_info.available_balance + self.get_total_unrealized_pnl() if self.account_info else (
                self.wallet_balance + self.get_total_unrealized_pnl()
            )
            if initial_balance == 0:
                return 0.0
            return (initial_balance - current_balance) / initial_balance
        except Exception as e:
            logger.error(f"Lỗi khi tính drawdown: {str(e)}")
            return 0.0

    def is_in_cooldown_mode(self) -> bool:
        """
        Kiểm tra xem danh mục có đang trong chế độ cooldown.

        Returns:
            True nếu trong chế độ cooldown.
        """
        try:
            if self.risk_manager:
                return self.risk_manager._is_in_cooldown()
            return self.get_drawdown() > 0.2  # Cooldown nếu drawdown > 20%
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra cooldown mode: {str(e)}")
            return False

    def get_open_positions(self) -> List[str]:
        """
        Lấy danh sách các symbol có vị thế mở.

        Returns:
            Danh sách symbol.
        """
        try:
            return [symbol for symbol, side_dict in self.positions.items() if any(pos.position_amt != 0 for pos in side_dict.values())]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách vị thế mở: {str(e)}")
            return []

    def get_position_pnl(self, symbol: str) -> float:
        """
        Tính PNL của vị thế cho symbol.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Tổng PNL (realized + unrealized).
        """
        try:
            if symbol not in self.positions:
                return 0.0
            return sum(pos.unrealized_profit + pos.realized_profit for pos in self.positions[symbol].values())
        except Exception as e:
            logger.error(f"Lỗi khi tính PNL cho {symbol}: {str(e)}")
            return 0.0

    def get_position_notional(self, symbol: str) -> float:
        """
        Tính giá trị danh nghĩa của vị thế.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Tổng notional.
        """
        try:
            if symbol not in self.positions:
                return 0.0
            return sum(pos.notional for pos in self.positions[symbol].values())
        except Exception as e:
            logger.error(f"Lỗi khi tính notional cho {symbol}: {str(e)}")
            return 0.0

    def get_position_open_time(self, symbol: str) -> int:
        """
        Lấy thời gian mở vị thế.

        Args:
            symbol: Cặp giao dịch.

        Returns:
            Timestamp mở vị thế (ms).
        """
        try:
            if symbol not in self.positions:
                return 0
            return min((pos.update_time for pos in self.positions[symbol].values() if pos.position_amt != 0), default=0)
        except Exception as e:
            logger.error(f"Lỗi khi lấy thời gian mở vị thế cho {symbol}: {str(e)}")
            return 0