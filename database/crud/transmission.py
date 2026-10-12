from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.transmission import Transmission
from database.schemas.filters import FilterCreate, FilterUpdate


class TransmissionService(BaseService[Transmission, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Transmission, session)
