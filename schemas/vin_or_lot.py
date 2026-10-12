from pydantic import Field

from auction_api.types.common import DefinedSiteEnum
from request_schemas.lot import SiteIn


class VinOrLotIn(SiteIn):
    site: DefinedSiteEnum | None = Field(None, description="Auction of vehicle")
    vin_or_lot: str

    @classmethod
    def validate_site(cls, v):
        return v
