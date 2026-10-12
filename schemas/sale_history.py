from datetime import datetime

from pydantic import BaseModel


class SaleHistoryOut(BaseModel):
    auction: str | None = None
    buyer_city: str | None = None
    buyer_country: str | None = None
    date: datetime | None = None
    final_bid: int | None = None
    lot_id: int | None = None
    status: str | None = None
    is_buy_now: bool | None = None
    vin: str | None = None
