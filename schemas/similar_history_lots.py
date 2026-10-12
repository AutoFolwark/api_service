from pydantic import BaseModel

from auction_api.types.common import SiteEnum


class SimilarHistoryLots(BaseModel):
    site: SiteEnum
    make: str
    model: str | None = None
    year: int | None = None
    vehicle_type: str | None = "Automobile"
