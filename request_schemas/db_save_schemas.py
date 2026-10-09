from pydantic import BaseModel, Field

class DBPaginationBase(BaseModel):
    page: int = 1
    size: int = 1000


class DBDateBase(BaseModel):
    date_to: str
    date_from: str
    sort: str | None = Field(default=None)

class DBAllLotsIn(DBPaginationBase):
    pass

class DBCurrentUpdateIn(DBPaginationBase, DBDateBase):
    only_with_auction_date: bool = False
    lot_id: int | None = Field(default=None)

class DBCurrentDeleteIn(DBDateBase):
    direction: str | None = Field(default=None)

class DBHistoryUpdateIn(DBPaginationBase, DBDateBase):
    period: int | None = Field(default=None)
    lot_id: int | None = Field(default=None)

