from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator
from requests.compat import has_simplejson

from auction_api.utils import AuctionApiUtils
from core.logger import logger


class FormGetType(str, Enum):
    HISTORY = "history"
    ACTIVE = "active"


class BasicLot(BaseModel):
    lot_id: Optional[int] = None
    site: Optional[int] = None
    base_site: Optional[str] = None
    salvage_id: Optional[int] = None
    odometer: Optional[int] = None
    price_new: Optional[int] = None
    price_future: Optional[int] = None
    price_reserve: Optional[int] = None
    current_bid: Optional[int] = None
    auction_date: Optional[datetime] = None
    cost_priced: Optional[int] = None
    cost_repair: Optional[int] = None
    year: Optional[int] = None
    cylinders: Optional[int] = None
    state: Optional[str] = None
    vehicle_type: Optional[str] = None
    auction_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    series: Optional[str] = None
    damage_pr: Optional[str] = None
    damage_sec: Optional[str] = None
    keys: Optional[str] = None
    odobrand: Optional[str] = None
    fuel: Optional[str] = None
    drive: Optional[str] = None
    transmission: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None
    title: Optional[str] = None
    vin: Optional[str] = None
    engine: Optional[str] = None
    engine_size: Optional[float] = None
    location: Optional[str] = None
    location_old: Optional[str] = None
    location_id: Optional[int] = None
    country: Optional[str] = None
    document: Optional[str] = None
    document_old: Optional[str] = None
    currency: Optional[str] = None
    seller: Optional[str] = None
    is_buynow: Optional[bool] = None
    iaai_360: Optional[str] = None
    copart_exterior_360: Optional[list[str]] = None
    copart_interior_360: Optional[str] = None
    video: Optional[str] = None
    link_img_hd: Optional[list[HttpUrl]] = None
    link_img_small: Optional[list[HttpUrl]] = None
    is_offsite: Optional[bool] = None
    location_offsite: Optional[str] = None
    link: Optional[HttpUrl] = None
    body_type: Optional[str] = None
    seller_type: Optional[str] = None
    vehicle_score: Optional[str] = None
    form_get_type: FormGetType = Field(default=FormGetType.HISTORY)

    @model_validator(mode="after")
    @classmethod
    def validate_together(cls, data):
        try:
            auction_date = data.auction_date
            if auction_date:
                now = datetime.now(UTC)
                if auction_date > now:
                    data.form_get_type = FormGetType.ACTIVE
                else:
                    data.form_get_type = FormGetType.HISTORY
            else:
                if hasattr(data, "sale_date"):
                    data.form_get_type = FormGetType.HISTORY
        except Exception as e:
            logger.exception(f"Failed to parse auction_date: {e}")
            data.form_get_type = FormGetType.HISTORY
        return data


class SaleHistoryItem(BaseModel):
    lot_id: int | None = None
    site: int | None = None
    base_site: str | None = None
    vin: str | None = None
    sale_status: str | None = None
    sale_date: datetime | None = None
    purchase_price: int | None = None
    is_buynow: bool | None = None
    buyer_state: str | None = None
    buyer_country: str | None = None
    vehicle_type: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_together(cls, data: dict):
        base_site = data.get("base_site")
        site = data.get("site")

        if not base_site:
            data["base_site"] = AuctionApiUtils.num_to_auction_name(site)

        return data


class BasicHistoryLot(BasicLot):
    sale_history: Optional[list[SaleHistoryItem]] = None
    sale_date: Optional[datetime] = None
    sale_status: Optional[str] = None
    purchase_price: Optional[int] = None
