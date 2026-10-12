from fastapi import APIRouter, Depends, Query

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot
from auction_api.utils import AuctionApiUtils
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn
from schemas.sale_history import SaleHistoryOut

sales_history_router = APIRouter()


@sales_history_router.get(
    "", response_model=list[SaleHistoryOut], description="Get sales history by lot id"
)
async def get_sales_history(
    data: LotByIDIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
) -> list[SaleHistoryOut]:
    result: BasicHistoryLot = await api.request_with_schema(
        AuctionApiClient.GET_LOT_HISTORY_BY_ID, data
    )
    sales_history = result.sale_history or []

    sales: list[SaleHistoryOut] = []
    for history in sales_history:
        sales.append(
            SaleHistoryOut(
                auction=AuctionApiUtils.num_to_auction_name(history.site).upper(),
                buyer_country=getattr(history, "buyer_country", None),
                date=history.sale_date,
                final_bid=history.purchase_price,
                lot_id=history.lot_id,
                status=getattr(
                    history, "status", getattr(history, "sale_status", None)
                ),
                is_buy_now=getattr(
                    history, "is_buy_now", getattr(history, "is_buynow", None)
                ),
                vin=history.vin,
            )
        )
    return sales
