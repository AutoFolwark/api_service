from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models import VehicleType
from database.schemas.filters import FilterCreate, FilterUpdate


class VehicleTypeService(BaseService[VehicleType, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(VehicleType, session)
