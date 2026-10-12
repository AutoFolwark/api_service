from pydantic import BaseModel, Field

from auction_api.types.common import SimpleSiteEnum


class TitleIndicatorsIn(BaseModel):
    site: SimpleSiteEnum = Field(..., description="Auction of vehicle")
    title_name: str = Field(..., description="Title name")


class TitleIndicatorsOut(BaseModel):
    color: str = Field(..., description="Title color")
