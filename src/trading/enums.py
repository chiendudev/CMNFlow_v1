from enum import Enum

class SymbolType(str, Enum):
    FUTURE = 'FUTURE'

class ContractType(str, Enum):
    PERPETUAL = 'PERPETUAL'
    CURRENT_MONTH = 'CURRENT_MONTH'
    NEXT_MONTH = 'NEXT_MONTH'
    CURRENT_QUARTER = 'CURRENT_QUARTER'
    NEXT_QUARTER = 'NEXT_QUARTER'
    PERPETUAL_DELIVERING = 'PERPETUAL_DELIVERING'

class ContractStatus(str, Enum):
    PENDING_TRADING = 'PENDING_TRADING'
    TRADING = 'TRADING'
    PRE_DELIVERING = 'PRE_DELIVERING'
    DELIVERING = 'DELIVERING'
    DELIVERED = 'DELIVERED'
    PRE_SETTLE = 'PRE_SETTLE'
    SETTLING = 'SETTLING'
    CLOSE = 'CLOSE'

class OrderStatus(str, Enum):
    NEW = 'NEW'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCELED = 'CANCELED'
    REJECTED = 'REJECTED'
    EXPIRED = 'EXPIRED'
    EXPIRED_IN_MATCH = 'EXPIRED_IN_MATCH'

class OrderType(str, Enum):
    LIMIT = 'LIMIT'
    MARKET = 'MARKET'
    STOP = 'STOP'
    STOP_MARKET = 'STOP_MARKET'
    TAKE_PROFIT = 'TAKE_PROFIT'
    TAKE_PROFIT_MARKET = 'TAKE_PROFIT_MARKET'
    TRAILING_STOP_MARKET = 'TRAILING_STOP_MARKET'

class OrderSide(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'

class PositionSide(str, Enum):
    BOTH = 'BOTH'
    LONG = 'LONG'
    SHORT = 'SHORT'

class TimeInForce(str, Enum):
    GTC = 'GTC'  # Good Till Cancel(GTC order valitidy is 1 year from placement)
    IOC = 'IOC'  # Immediate or Cancel
    FOK = 'FOK'  # fill or kill
    GTX = 'GTX'  # Good Till Crossing (Post Only)
    GTD = 'GTD'  # Good Till Date

class WorkingType(str, Enum):
    MARK_PRICE = 'MARK_PRICE'
    CONTRACT_PRICE = 'CONTRACT_PRICE'

class NewOrderResponseType(str, Enum):  # (newOrderRespType)
    ACK = 'ACK'
    RESULT = 'RESULT'

class KlineIntervals(str, Enum):
    m1 = '1m'
    m3 = '3m'
    m5 = '5m'
    m15 = '15m'
    m30 = '30m'
    h1 = '1h'
    h2 = '2h'
    h4 = '4h'
    h6 = '6h'
    h8 = '8h'
    h12 = '12h'
    d1 = '1d'
    d3 = '3d'
    w1 = '1w'
    M1 = '1M'

class STPMode(str, Enum):  # (selfTradePreventionMode)
    EXPIRE_TAKER = 'EXPIRE_TAKER'
    EXPIRE_BOTH = 'EXPIRE_BOTH'
    EXPIRE_MAKER = 'EXPIRE_MAKER'
    NONE = 'NONE'

class TradeMode(str, Enum):
    HEDGE = 'HEDGE'
    ONE_WAY = 'ONE_WAY'

class MarginType(str, Enum):
    ISOLATED = 'ISOLATED'
    CROSSED = 'CROSSED'