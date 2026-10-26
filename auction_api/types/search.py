from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from auction_api.types.common import SiteEnum, SiteIn
from auction_api.types.db_lot import DBDeleteLot, DBUpdateLot
from auction_api.types.lot import BasicHistoryLot, BasicLot


class BasicPaginationInfo(BaseModel):
    size: int
    page: int
    pages: int
    count: int


class DBManyLots(BasicPaginationInfo):
    data: list[DBUpdateLot]


class DBManyDeletedLots(BaseModel):
    data: list[DBDeleteLot]


class DecodedSearch(BaseModel):
    query: str
    year: int | None = None
    make: str | None = None
    make_slug: str | None = None
    model: str | None = None
    model_slug: str | None = None
    unrecognized: list[str] = []


class BasicManyCurrentLots(BasicPaginationInfo):
    data: list[BasicLot]
    decoded_search: DecodedSearch | None = None


class BasicManyHistoryLot(BasicPaginationInfo):
    data: list[BasicHistoryLot]
    decoded_search: DecodedSearch | None = None


class SortEnum(str, Enum):
    """Sort field enumeration"""

    AUCTION_DATE = "auction_date"
    CREATED_AT = "created_at"


class DirectionEnum(str, Enum):
    """Sort direction enumeration"""

    ASC = "ASC"
    DESC = "DESC"


class VehicleTypeEnum(str, Enum):
    AUTOMOBILE = "automobile"
    TRUCK = "truck"
    TRAILERS = "trailers"
    MOTORCYCLE = "motorcycle"
    BOAT = "boat"
    ATV = "atv"
    WATERCRAFT = "watercraft"
    BUS = "bus"
    INDUSTRIAL_EQUIPMENT = "industrial_equipment"
    JET_SKY = "jet_sky"
    OTHER = "other"


class SellerTypeEnum(str, Enum):
    INSURANCE = "insurance"
    DEALER = "dealer"


class CommonSearchParams(SiteIn):
    search: str | None = Field(
        None,
        min_length=2,
        max_length=100,
        exclude=True,
        description="Free text, e.g. '2016 camry' or 'bmw 1 series 2010'",
    )
    make: str | None = Field(None, description="Vehicle make")
    model: str | None = Field(None, description="Vehicle model")
    vehicle_type: str | None = Field(None, description="Vehicle type")
    year_from: int | None = Field(None, ge=1900, le=2030, description="Year from")
    year_to: int | None = Field(None, ge=1900, le=2030, description="Year to")
    auction_date_from: datetime | None = Field(
        default=None,
        description="Auction date from, '2025-08-18'",
        examples=["2025-08-18"],
    )
    auction_date_to: datetime | None = Field(
        None, description="Auction date to, '2025-08-18'", examples=["2025-08-18"]
    )

    transmission: list[str] | None = Field(None, description="Transmission types")
    status: list[str] | None = Field(None, description="Vehicle statuses")

    drive: list[str] | None = Field(None, description="Drive types")
    color: str | None = Field(None, description="Exterior color")
    damage_pr: list[str] | None = Field(None, description="Primary damage types")
    engine_size_from: float | None = Field(None, ge=0, description="Engine size from, liters")
    engine_size_to: float | None = Field(None, ge=0, description="Engine size to, liters")

    document: list[str] | None = Field(None, description="Document types")
    odometer_min: int | None = Field(None, ge=0, description="Minimum odometer")
    odometer_max: int | None = Field(None, ge=0, description="Maximum odometer")
    seller_type: SellerTypeEnum | None = Field(None, description="Seller type")
    sort: SortEnum | None = Field(SortEnum.AUCTION_DATE, description="Sort field")
    direction: DirectionEnum | None = Field(
        DirectionEnum.ASC, description="Sort direction"
    )

    page: int | None = Field(1, ge=1, description="Page number")
    size: int | None = Field(10, ge=1, le=30, description="Lots per page (max 30)")

    model_config = ConfigDict(use_enum_values=True)


class CurrentSearchParams(CommonSearchParams):
    buy_now: bool | None = Field(None, description="Get only Buy Now lots")
    fuel: list[str] | None = Field(None, description="Fuel types")
    auction_type: Literal["timed"] | None = Field(
        None, description="Auction type (only for site=2)"
    )

    @model_validator(mode="after")
    @classmethod
    def validate_auction_type_site(cls, data: "CurrentSearchParams"):
        if data.auction_type is not None and data.site != SiteEnum.IAAI_NUM:
            raise ValueError("auction_type is only supported for site=2")
        return data


class HistorySearchParams(CommonSearchParams):
    pass
