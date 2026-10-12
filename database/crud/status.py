from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.status import Status
from database.schemas.filters import FilterCreate, FilterUpdate


class StatusService(BaseService[Status, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Status, session)
