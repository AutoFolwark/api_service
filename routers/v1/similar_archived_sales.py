from fastapi import APIRouter, Depends, Query

from auction_api.api import AuctionApiClient
from auction_api.types.search import BasicManyCurrentLots, HistorySearchParams
from core.logger import logger
from dependencies.auction_api_service import get_auction_api_service
from schemas.similar_archived_sales import SimilarArchivedSalesPricesOut
from schemas.similar_history_lots import SimilarHistoryLots
from services.field_translations import get_locale, translate_lot_response

similar_sales_router = APIRouter()


def _build_history_search_params(data: SimilarHistoryLots) -> HistorySearchParams:
    year_from = data.year - 5 if data.year is not None else None
    year_to = data.year + 5 if data.year is not None else None
    return HistorySearchParams(
        make=data.make,
        model=data.model,
        year_from=year_from,
        year_to=year_to,
        vehicle_type=data.vehicle_type,
        site=data.site,
    )


@similar_sales_router.get("", response_model=BasicManyCurrentLots)
async def get_similar_sales(
    data: SimilarHistoryLots = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
    locale: str = Depends(get_locale),
):
    params = _build_history_search_params(data)
    logger.debug(
        "New request to get many history lots", extra={"data": params.model_dump()}
    )
    result = await api.request_with_schema(AuctionApiClient.GET_HISTORY_LOTS, params)
    return translate_lot_response(result, locale)


@similar_sales_router.get("/prices", response_model=SimilarArchivedSalesPricesOut)
async def get_similar_sales_prices(
    data: SimilarHistoryLots = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    params = _build_history_search_params(data)
    logger.debug(
        "New request to get similar archived sales prices",
        extra={"data": params.model_dump()},
    )

    result = await api.request_with_schema(AuctionApiClient.GET_HISTORY_LOTS, params)

    prices: list[int] = []
    for lot in result.data:
        price = getattr(lot, "purchase_price", None)
        if isinstance(price, int) and price > 0:
            prices.append(price)

    if not prices:
        return SimilarArchivedSalesPricesOut()

    return SimilarArchivedSalesPricesOut(
        min_price=min(prices),
        avg_price=round(sum(prices) / len(prices), 2),
        max_price=max(prices),
        processed_lots=len(prices),
    )
