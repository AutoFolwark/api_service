from pydantic import BaseModel, Field, RootModel

from auction_api.types.common import DefinedSiteEnum, SiteIn


class LotByIDIn(SiteIn):
    site: DefinedSiteEnum | None = Field(None, description="Auction of vehicle")
    lot_id: int = Field(..., description="Lot id")


class LotByVINIn(SiteIn):
    vin: str = Field(..., description="VIN of vehicle")


class GetAveragedPriceIn(BaseModel):
    make: str = Field(..., description="Make of vehicle")
    model: str = Field(..., description="Model of vehicle")
    year_from: int | None = Field(None, description="Year of vehicle")
    year_to: int | None = Field(None, description="Year of vehicle")
    period: int = Field(..., description="Period in months")


class CurrentBidOut(BaseModel):
    pre_bid: int


class StatItem(BaseModel):
    total: int | None = Field(None)
    min: int | None = Field(None)
    max: int | None = Field(None)
    count: int | None = Field(None)


class StatisticsData(RootModel[dict[str, StatItem]]):
    pass
