from src.core.settings import Settings
from src.exchange.rest.account_client import AccountClient
from src.trading.enums import PositionSide
from dataclasses import dataclass
from typing import List, Dict, Any
from aiohttp import ClientSession

@dataclass
class Asset:
    asset: str = ''
    wallet_balance: float = 0.0
    unrealized_profit: float = 0.0
    margin_balance: float = 0.0
    maint_margin: float = 0.0
    initial_margin: float = 0.0
    position_initial_margin: float = 0.0
    open_order_initial_margin: float = 0.0
    cross_wallet_balance: float = 0.0
    cross_un_pnl: float = 0.0
    available_balance: float = 0.0
    max_withdraw_amount: float = 0.0
    update_time: int = 0.0

@dataclass
class OpenPosition:
    symbol: str
    position_side: PositionSide = PositionSide.BOTH
    position_amt: float = 0.0
    unrealized_profit: float = 0.0
    isolated_margin: float = 0.0
    notional: float = 0.0
    isolated_wallet: float = 0.0
    initial_margin: float = 0.0
    maint_margin: float = 0.0
    update_time:float = 0.0

@dataclass
class FutureBalance:
    account_alias: str = ''
    asset: str = ''
    balance: float = 0.0
    cross_wallet_balance: float = 0.0
    cross_un_pnl: float = 0.0
    available_balance: float = 0.0
    max_withdraw_amount: float = 0.0
    margin_available: bool = True
    update_time: int = 0

class AccountInfo:
    def __init__(self, settings: Settings, sessions: ClientSession, deposit: float = None):
        self.deposit = deposit  # for testing only

        self.settings = settings
        self.client = AccountClient(settings=settings, session=sessions)
        self.total_initial_margin: float = 0.0
        self.total_maint_margin: float = 0.0
        self.total_wallet_balance: float = 0.0
        self.total_unrealized_profit: float = 0.0
        self.total_margin_balance: float = 0.0
        self.total_position_initial_margin: float = 0.0
        self.total_open_order_initial_margin: float = 0.0
        self.total_cross_wallet_balance: float = 0.0
        self.total_cross_un_pnl: float = 0.0
        self.available_balance: float = 0.0
        self.max_withdraw_amount: float = 0.0
        self.assets: List[Asset] = []
        self.open_positions: List[OpenPosition] = []
        self.future_balance: Dict[str, FutureBalance] = {}

    async def initial(self):
        future_balance_data = await self.client.get_futures_account_balance_v3()
        account_info = await self.client.get_account_information_v3()
        self.update_from_account_data(account_info)
        self.update_future_balance(future_balance_data)

    def update_future_balance(self, data: List[Dict[str, Any]]):
        if not data:
            raise ValueError(f"Không thể lấy dữ liệu future account balance {data}")
        for balance in data:
            future_balance = FutureBalance(
                account_alias=balance['accountAlias'],
                asset=balance['asset'],
                balance=float(balance['balance']),
                cross_wallet_balance=float(balance['crossWalletBalance']),
                cross_un_pnl=float(balance['crossUnPnl']),
                available_balance=float(balance['availableBalance']),
                max_withdraw_amount=float(balance['maxWithdrawAmount']),
                margin_available=balance['marginAvailable'],
                update_time=balance['updateTime']
            )
            asset = future_balance.asset
            if asset not in self.future_balance:
                self.future_balance[asset] = future_balance
            else:
                self.future_balance[asset] = future_balance

    def update_from_account_data(self, data: Dict[str, Any]):
        self.total_initial_margin = float(data["totalInitialMargin"])
        self.total_maint_margin = float(data["totalMaintMargin"])
        self.total_wallet_balance = float(data["totalWalletBalance"])
        self.total_unrealized_profit = float(data["totalUnrealizedProfit"])
        self.total_margin_balance = float(data["totalMarginBalance"])
        self.total_position_initial_margin = float(data["totalPositionInitialMargin"])
        self.total_open_order_initial_margin = float(data["totalOpenOrderInitialMargin"])
        self.total_cross_wallet_balance = float(data["totalCrossWalletBalance"])
        self.total_cross_un_pnl = float(data["totalCrossUnPnl"])
        self.available_balance = float(data["availableBalance"])
        self.max_withdraw_amount = float(data["maxWithdrawAmount"])
        self.assets = [Asset(**{
            "asset": asset["asset"],
            "wallet_balance": float(asset["walletBalance"]),
            "unrealized_profit": float(asset["unrealizedProfit"]),
            "margin_balance": float(asset["marginBalance"]),
            "maint_margin": float(asset["maintMargin"]),
            "initial_margin": float(asset["initialMargin"]),
            "position_initial_margin": float(asset["positionInitialMargin"]),
            "open_order_initial_margin": float(asset["openOrderInitialMargin"]),
            "cross_wallet_balance": float(asset["crossWalletBalance"]),
            "cross_un_pnl": float(asset["crossUnPnl"]),
            "available_balance": float(asset["availableBalance"]),
            "max_withdraw_amount": float(asset["maxWithdrawAmount"]),
            "update_time": asset["updateTime"],
        }) for asset in data.get("assets", [])]
        self.open_positions = [OpenPosition(** {
            'symbol': pos['symbol'],
            'position_side': pos['positionSide'],
            'position_amt': float(pos['positionAmt']),
            'unrealized_profit': float(pos['unrealizedProfit']),
            'isolated_margin': float(pos['isolatedMargin']),
            'notional': float(pos['notional']),
            'isolated_wallet': float(pos['isolatedWallet']),
            'initial_margin': float(pos['initialMargin']),
            'maint_margin': float(pos['maintMargin']),
            'update_time': int(pos['updateTime'])
        }) for pos in data.get('positions', [])]


























