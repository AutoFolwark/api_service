from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.types.common import SimpleSiteEnum
from database.crud.base import BaseService
from database.models.title_indicators import TitleIndicators
from database.schemas.title_indicators import (
    TitleIndicatorCreate,
    TitleIndicatorUpdate,
)


class TitleIndicatorsService(
    BaseService[TitleIndicators, TitleIndicatorCreate, TitleIndicatorUpdate]
):
    def __init__(self, session: AsyncSession):
        super().__init__(TitleIndicators, session)

    async def get_by_title_name_n_site(
        self, site: SimpleSiteEnum, title_name: str
    ) -> TitleIndicators | None:
        stmt = (
            select(TitleIndicators)
            .where(
                TitleIndicators.site == site.value,
                TitleIndicators.title_name == title_name,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
