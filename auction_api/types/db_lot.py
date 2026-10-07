from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl


class DBUpdateLot(BaseModel):
    id: Optional[str] = None
    lot_id: Optional[int] = None
    site: Optional[int] = None
    base_site: Optional[str] = None
    salvage_id: Optional[int] = None
    auction_id: Optional[str] = None
    odometer: Optional[int] = None
    price_new: Optional[int] = None
    price_future: Optional[int] = None
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
    loss: Optional[str] = None
    keys: Optional[str] = None
    odobrand: Optional[str] = None
    fuel: Optional[str] = None
    drive: Optional[str] = None
    transmission: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None
    presale_status: Optional[str] = None
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
    seller_type_model: Optional[str] = None
    seller_type: Optional[str] = None
    seller_detailed_type: Optional[str] = None
    seller: Optional[str] = None
    vehicle_score: Optional[str] = None
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    branch_number: Optional[int | str] = None
    branch_link: Optional[HttpUrl | str] = None
    title_brand: Optional[str] = None
    airbag: Optional[str] = None
    tenant: Optional[str] = None
    odometer_index: Optional[int | str] = None
    timed_auction_close_date: Optional[datetime] = None
    is_tbo: Optional[bool] = None
    is_title_pending: Optional[bool] = None
    zip: Optional[int | str] = None
    lane: Optional[str] = None
    sort_order: Optional[int] = None
    copart_yard_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DBDeleteLot(BaseModel):
    id: str
    lot_id: int
    site: int
    created_at: datetime
    updated_at: datetime