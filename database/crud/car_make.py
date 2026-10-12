from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models import VehicleType
from database.models.car_make import Make
from database.schemas.filters import FilterCreate, FilterUpdate


class MakeService(BaseService[Make, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Make, session)

    async def get_makes_by_vehicle_type(
        self, vehicle_type: VehicleType
    ) -> Sequence[Make]:
        result = await self.session.execute(
            select(Make)
            .where(Make.vehicle_type_id == vehicle_type.id)
            .order_by(Make.name.asc())
        )
        return result.scalars().all()

    async def get_make_by_slug_vehicle_type(
        self, slug: str, vehicle_type: VehicleType
    ) -> Make | None:
        result = await self.session.execute(
            select(Make)
            .where(Make.slug == slug, Make.vehicle_type_id == vehicle_type.id)
            .limit(1)
        )
        return result.scalar_one_or_none()
