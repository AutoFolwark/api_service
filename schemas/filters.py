from pydantic import BaseModel

from database.schemas.filters import FilterRead


class AllFiltersOut(BaseModel):
    damage: list[FilterRead]
    transmission: list[FilterRead]
    document: list[FilterRead]
    drive: list[FilterRead]
    status: list[FilterRead]
    vehicle_type: list[FilterRead]
