from typing import List, Optional, Any
from pydantic import BaseModel


class Filter(BaseModel):
    filterType: str
    tickSize: Optional[str] = None
    maxPrice: Optional[str] = None
    minPrice: Optional[str] = None
    minQty: Optional[str] = None
    stepSize: Optional[str] = None
    maxQty: Optional[str] = None
    limit: Optional[int] = None
    notional: Optional[str] = None
    multiplierDown: Optional[str] = None
    multiplierUp: Optional[str] = None
    multiplierDecimal: Optional[str] = None
    positionControlSide: Optional[str] = None


class ContractInfo(BaseModel):
    symbol: str
    pair: str
    contractType: str
    deliveryDate: int
    onboardDate: int
    status: str
    maintMarginPercent: str
    requiredMarginPercent: str
    baseAsset: str
    quoteAsset: str
    marginAsset: str
    pricePrecision: int
    quantityPrecision: int
    baseAssetPrecision: int
    quotePrecision: int
    underlyingType: str
    underlyingSubType: List[Any]  # hoặc List[str]
    triggerProtect: str
    liquidationFee: str
    marketTakeBound: str
    maxMoveOrderLimit: int
    filters: List[Filter]
    orderTypes: List[str]
    timeInForce: List[str]
    permissionSets: List[str]


def parse_contracts(json_data: List[dict]) -> List[ContractInfo]:
    """
    Chuyển danh sách dict contract info thành danh sách ContractInfo model
    """
    return [ContractInfo.model_validate(item) for item in json_data]


# Ví dụ dùng:
# import json
# data = json.loads(json_string)
# contracts = parse_contracts(data)
# print(contracts[0].symbol)
