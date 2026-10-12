from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.drive import Drive
from database.schemas.filters import FilterCreate, FilterUpdate


class DriveService(BaseService[Drive, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Drive, session)
