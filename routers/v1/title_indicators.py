from fastapi import APIRouter
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.title_indicators import TitleIndicatorsService
from database.db.session import get_async_db
from request_schemas.title_indicators import TitleIndicatorsIn, TitleIndicatorsOut

title_indicators_router = APIRouter()


@title_indicators_router.get(
    "",
    response_model=TitleIndicatorsOut,
    description="Get title color dots, available colors:\n"
    "grey, green, yellow, red, red red, black",
)
async def get_title_indicators(
    data: TitleIndicatorsIn = Depends(), db: AsyncSession = Depends(get_async_db)
):
    service = TitleIndicatorsService(db)
    result = await service.get_by_title_name_n_site(data.site, data.title_name)
    if not result or not result.status:
        title_name = data.title_name.lower()
        if title_name.startswith("salvage"):
            return TitleIndicatorsOut(color="green")
        return TitleIndicatorsOut(color="grey")
    return TitleIndicatorsOut(color=result.status)
