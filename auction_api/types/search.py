from datetime import datetime
from enum import Enum

from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator

from auction_api.types.common import SiteIn, SiteEnum
from auction_api.types.db_lot import DBUpdateLot, DBDeleteLot
from auction_api.types.lot import BasicLot, BasicHistoryLot


class BasicPaginationInfo(BaseModel):
    size: int
    page: int
    pages: int
    count: int


class DBManyLots(BasicPaginationInfo):
    data: list[DBUpdateLot]

class DBManyDeletedLots(BaseModel):
    data: list[DBDeleteLot]


class BasicManyCurrentLots(BasicPaginationInfo):
    data: list[BasicLot]

class BasicManyHistoryLot(BasicPaginationInfo):
    data: list[BasicHistoryLot]


class SortEnum(str, Enum):
    """Sort field enumeration"""
    AUCTION_DATE = "auction_date"
    CREATED_AT = "created_at"


class DirectionEnum(str, Enum):
    """Sort direction enumeration"""
    ASC = "ASC"
    DESC = "DESC"

class VehicleTypeEnum(str, Enum):
    AUTOMOBILE = 'automobile'
    TRUCK = 'truck'
    TRAILERS = 'trailers'
    MOTORCYCLE = 'motorcycle'
    BOAT = 'boat'
    ATV = 'atv'
    WATERCRAFT = 'watercraft'
    BUS = 'bus'
    INDUSTRIAL_EQUIPMENT = 'industrial_equipment'
    JET_SKY = 'jet_sky'
    OTHER = 'other'


class SellerTypeEnum(str, Enum):
    INSURANCE = 'insurance'
    DEALER = 'dealer'




class CommonSearchParams(SiteIn):
    make: str | None = Field(None, description="Vehicle make")
    model: str | None = Field(None, description="Vehicle model")
    vehicle_type: str | None = Field(None, description="Vehicle type")
    year_from: int | None = Field(None, ge=1900, le=2030, description="Year from")
    year_to: int | None = Field(None, ge=1900, le=2030, description="Year to")
    auction_date_from: datetime | None = Field(default=None, description="Auction date from, '2025-08-18'",
                                               examples=['2025-08-18'])
    auction_date_to: datetime | None = Field(None, description="Auction date to, '2025-08-18'",
                                             examples=['2025-08-18'])

    transmission: list[str] | None = Field(None, description="Transmission types")
    status: list[str] | None = Field(None, description="Vehicle statuses")

    drive: list[str] | None = Field(None, description="Drive types")
    damage_pr: list[str] | None = Field(None, description="Primary damage types")

    document: list[str] | None = Field(None, description="Document types")
    odometer_min: int | None = Field(None, ge=0, description="Minimum odometer")
    odometer_max: int | None = Field(None, ge=0, description="Maximum odometer")
    seller_type: SellerTypeEnum | None = Field(None, description="Seller type")
    sort: SortEnum | None = Field(SortEnum.AUCTION_DATE, description="Sort field")
    direction: DirectionEnum | None = Field(DirectionEnum.ASC, description="Sort direction")

    page: int | None = Field(1, ge=1, description="Page number")
    size: int | None = Field(10, ge=1, le=30, description="Lots per page (max 30)")

    model_config = ConfigDict(use_enum_values=True)




class CurrentSearchParams(CommonSearchParams):
    buy_now: bool | None = Field(None, description="Get only Buy Now lots")
    fuel: list[str] | None = Field(None, description="Fuel types")
    auction_type: Literal['timed'] | None = Field(
        None,
        description="Auction type (only for site=2)"
    )

    @model_validator(mode="after")
    @classmethod
    def validate_auction_type_site(cls, data: "CurrentSearchParams"):
        if data.auction_type is not None and data.site != SiteEnum.IAAI_NUM:
            raise ValueError("auction_type is only supported for site=2")
        return data

class HistorySearchParams(CommonSearchParams):
    pass





