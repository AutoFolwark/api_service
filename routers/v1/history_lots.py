from fastapi import APIRouter, Depends, Query
from fastapi_cache import default_key_builder
from fastapi_cache.decorator import cache
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot
from auction_api.types.search import BasicManyHistoryLot, HistorySearchParams
from core.logger import logger
from database.db.session import get_async_db
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn, LotByVINIn
from services.transform_slugs import transform_slugs

history_cars_router = APIRouter()


@history_cars_router.get(
    "/vin", response_model=BasicHistoryLot, description="Get history lot by vin"
)
@cache(expire=60 * 60, key_builder=default_key_builder)
async def get_history_by_vin(
    data: LotByVINIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug(
        "New request to get history lot by vin",
        extra={"data": data.model_dump(mode="json")},
    )
    return await api.request_with_schema(AuctionApiClient.GET_LOT_HISTORY_BY_VIN, data)


@history_cars_router.get(
    "/lot-id", response_model=BasicHistoryLot, description="Get history lot by lot id"
)
@cache(expire=60 * 60, key_builder=default_key_builder)
async def get_history_by_vin(
    data: LotByIDIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug(
        "New request to get history lot by lot id",
        extra={"data": data.model_dump(mode="json")},
    )
    return await api.request_with_schema(
        AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, lot_id=data.lot_id
    )


@history_cars_router.get(
    "", response_model=BasicManyHistoryLot, description="Get history lots"
)
@cache(expire=60 * 60, key_builder=default_key_builder)
async def get_history_lots(
    data: HistorySearchParams = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    data = await transform_slugs(data, db)
    logger.debug(
        "New request to get many history lots",
        extra={"data": data.model_dump(mode="json")},
    )
    return await api.request_with_schema(AuctionApiClient.GET_HISTORY_LOTS, data)
