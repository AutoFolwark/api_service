from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models import Damage
from database.schemas.filters import FilterCreate, FilterUpdate


class DamageService(BaseService[Damage, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Damage, session)
