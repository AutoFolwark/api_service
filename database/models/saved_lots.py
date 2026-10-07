from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.orm import mapped_column, Mapped

from database.models import Base


class SavedLots(Base):

    __tablename__ = "saved_lots"
    __table_args__ = (
        Index("ix_saved_lots_lot_id_site", "lot_id", "site", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    lot_id: Mapped[str] = mapped_column(String, nullable=False)
    site: Mapped[int] = mapped_column(nullable=False)
    base_site: Mapped[Optional[str]] = mapped_column(String(16))
    salvage_id: Mapped[Optional[int]]
    auction_id: Mapped[Optional[str]]
    odometer: Mapped[Optional[int]]
    price_new: Mapped[Optional[int]]
    price_future: Mapped[Optional[int]]
    current_bid: Mapped[Optional[int]]
    auction_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cost_priced: Mapped[Optional[int]]
    cost_repair: Mapped[Optional[int]]
    year: Mapped[Optional[int]]
    cylinders: Mapped[Optional[int]]
    state: Mapped[Optional[str]]
    vehicle_type: Mapped[Optional[str]]
    auction_type: Mapped[Optional[str]]
    make: Mapped[Optional[str]]
    model: Mapped[Optional[str]]
    series: Mapped[Optional[str]]
    damage_pr: Mapped[Optional[str]]
    damage_sec: Mapped[Optional[str]]
    loss: Mapped[Optional[str]]
    keys: Mapped[Optional[str]]
    odobrand: Mapped[Optional[str]]
    fuel: Mapped[Optional[str]]
    drive: Mapped[Optional[str]]
    transmission: Mapped[Optional[str]]
    color: Mapped[Optional[str]]
    status: Mapped[Optional[str]]
    presale_status: Mapped[Optional[str]]
    title: Mapped[Optional[str]]
    vin: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    engine: Mapped[Optional[str]]
    engine_size: Mapped[Optional[float]]
    location: Mapped[Optional[str]]
    location_old: Mapped[Optional[str]]
    location_id: Mapped[Optional[int]]
    country: Mapped[Optional[str]]
    document: Mapped[Optional[str]]
    document_old: Mapped[Optional[str]]
    currency: Mapped[Optional[str]] = mapped_column(String(8))
    is_buynow: Mapped[Optional[bool]]
    iaai_360: Mapped[Optional[str]]
    copart_exterior_360: Mapped[Optional[list[str]]] = mapped_column(JSON)
    copart_interior_360: Mapped[Optional[str]]
    video: Mapped[Optional[str]]
    link_img_hd: Mapped[Optional[list[str]]] = mapped_column(JSON)
    link_img_small: Mapped[Optional[list[str]]] = mapped_column(JSON)
    is_offsite: Mapped[Optional[bool]]
    location_offsite: Mapped[Optional[str]]
    link: Mapped[Optional[str]]
    body_type: Mapped[Optional[str]]
    seller_type_model: Mapped[Optional[str]]
    seller_type: Mapped[Optional[str]]
    seller_detailed_type: Mapped[Optional[str]]
    seller: Mapped[Optional[str]]
    vehicle_score: Mapped[Optional[str]]
    notes: Mapped[Optional[str]]
    latitude: Mapped[Optional[float]]
    longitude: Mapped[Optional[float]]
    branch_number: Mapped[Optional[str]]
    branch_link: Mapped[Optional[str]]
    title_brand: Mapped[Optional[str]]
    airbag: Mapped[Optional[str]]
    tenant: Mapped[Optional[str]]
    odometer_index: Mapped[Optional[str]]
    timed_auction_close_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_tbo: Mapped[Optional[bool]]
    is_title_pending: Mapped[Optional[bool]]
    zip: Mapped[Optional[str]]
    lane: Mapped[Optional[str]]
    sort_order: Mapped[Optional[int]]
    copart_yard_name: Mapped[Optional[str]]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    is_deleted: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
