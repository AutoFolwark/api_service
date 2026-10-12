from typing import Optional

from pydantic import BaseModel, ConfigDict


class FilterCreate(BaseModel):
    name: str


class FilterUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None


class FilterRead(FilterCreate):
    id: int
    slug: str

    model_config = ConfigDict(from_attributes=True)
