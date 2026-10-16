from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi_cache import default_key_builder
from fastapi_cache.decorator import cache
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.common import DefinedSiteEnum
from auction_api.types.lot import BasicHistoryLot, BasicLot
from auction_api.types.search import BasicManyCurrentLots, CurrentSearchParams
from auction_api.utils import AuctionApiUtils, get_lot_vin_or_lot_id
from core.logger import logger
from database.db.session import get_async_db
from database.models.saved_lots import SavedLots
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import CurrentBidOut, LotByIDIn
from schemas.vin_or_lot import VinOrLotIn
from services.search_query_decoder import apply_decoded_search, decode_search_query
from services.transform_slugs import transform_slugs

cars_router = APIRouter()

_SAVED_LOT_RESPONSE_FIELDS = frozenset(BasicLot.model_fields) & {
    column.name for column in SavedLots.__table__.columns
}


async def _get_lots_from_db(
    db: AsyncSession,
    site: DefinedSiteEnum | None,
    vin_or_lot: str,
) -> BasicLot | list[BasicLot] | None:
    statement = select(SavedLots).where(SavedLots.is_deleted.is_(False))
    if vin_or_lot.isdigit():
        statement = statement.where(SavedLots.lot_id == vin_or_lot)
    else:
        statement = statement.where(SavedLots.vin == vin_or_lot)
    if site is not None:
        site_num = AuctionApiUtils.normalize_auction_to_num(site)
        if site_num is not None and site_num != AuctionApiUtils.AUCTION_NUM["all"]:
            statement = statement.where(SavedLots.site == site_num)
    statement = statement.order_by(
        SavedLots.auction_date.desc().nulls_last(), SavedLots.id.desc()
    )
    rows = (await db.execute(statement)).scalars().all()
    if not rows:
        return None
    try:
        lots = [BasicLot.model_validate(row) for row in rows]
    except (ValidationError, ValueError):
        logger.exception(
            "Failed to map saved lot to BasicLot", extra={"vin_or_lot": vin_or_lot}
        )
        return None
    return lots[0] if len(lots) == 1 else lots


@cars_router.get(
    "/vin-or-lot-id",
    response_model=list[BasicLot] | list[BasicHistoryLot] | BasicLot | BasicHistoryLot,
    description="Get lot by vin or lot id",
)
@cache(expire=60 * 15, key_builder=default_key_builder)
async def get_by_lot_id_or_vin(
    data: VinOrLotIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
    db: AsyncSession = Depends(get_async_db),
):
    logger.debug(
        "New request to get lot by vin or lot",
        extra={"data": data.model_dump(mode="json")},
    )
    logger.debug("Looking up for lot in db first")

    vin_or_lot = data.vin_or_lot.replace(" ", "").upper()
    lots = await _get_lots_from_db(db, data.site, vin_or_lot)
    if lots is not None:
        return lots

    logger.debug(
        "Lot not found in db, requesting auction api", extra={"vin_or_lot": vin_or_lot}
    )
    return await get_lot_vin_or_lot_id(api, data.site, vin_or_lot)


@cars_router.get(
    "/current-bid",
    response_model=CurrentBidOut,
    description="Get current bid for lot by its lot_id",
)
@cache(expire=60 * 5, key_builder=default_key_builder)
async def get_current_bid(
    data: LotByIDIn = Query(),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug(
        "New request to get current bid by lot id",
        extra={"data": data.model_dump(mode="json")},
    )
    return await api.request_with_schema(api.GET_CURRENT_BID_FOR_LOT, data)


@cars_router.get("", response_model=BasicManyCurrentLots)
@cache(expire=60 * 60, key_builder=default_key_builder)
async def get_current_lots(
    api: AuctionApiClient = Depends(get_auction_api_service),
    db: AsyncSession = Depends(get_async_db),
    search_params: CurrentSearchParams = Query(...),
):
    decoded = None
    if search_params.search:
        decoded = await decode_search_query(
            search_params.search,
            db,
            vehicle_type=search_params.vehicle_type,
        )
        apply_decoded_search(search_params, decoded)
    if not search_params.auction_date_from:
        search_params.auction_date_from = datetime.now(UTC)

    data = await transform_slugs(search_params, db)
    logger.debug(
        "New request to get many current lots",
        extra={"data": data.model_dump(mode="json")},
    )
    result = await api.request_with_schema(api.GET_CURRENT_LOTS, data)
    result.decoded_search = decoded
    return result
