from pydantic import BaseModel, Field


class DBRequestsBase(BaseModel):
    page: int = 1
    size: int = 1000
    sort: str | None = Field(default=None)

    date_to: str = ''
    date_from: str = ''


class DBCurrentUpdateIn(DBRequestsBase):
    only_with_auction_date: bool = False
    lot_id: int | None = Field(default=None)

class DBCurrentDeleteIn(DBRequestsBase):
    direction: str | None = Field(default=None)

class DBHistoryUpdateIn(DBRequestsBase):
    period: int | None = Field(default=None)
    lot_id: int | None = Field(default=None)

