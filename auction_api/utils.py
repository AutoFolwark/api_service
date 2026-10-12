from datetime import datetime
from typing import TYPE_CHECKING, Union

from pydantic_core import PydanticCustomError
from rfc9457 import NotFoundProblem

from core.logger import logger
from request_schemas.lot import LotByIDIn, LotByVINIn

if TYPE_CHECKING:
    from auction_api.api import AuctionApiClient
    from auction_api.types.search import SiteEnum


class AuctionApiUtils:
    AUCTION_NUM = {"copart": 1, "iaai": 2, "all": 3}

    @classmethod
    def num_to_auction_name(cls, num: int) -> str:
        for key, value in cls.AUCTION_NUM.items():
            if num == value:
                return key
        raise PydanticCustomError("wrong_auction_number", "Wrong auction number")

    @classmethod
    def auction_name_to_num(cls, auction_name: str) -> int:
        num = cls.AUCTION_NUM.get(auction_name.lower())
        if num is None:
            raise PydanticCustomError("wrong_auction_name", "Wrong auction name")
        return num

    @classmethod
    def normalize_auction_to_num(cls, auction: Union[str, int]) -> int | None:
        if auction is None:
            return auction
        if isinstance(auction, str) and not auction.isdigit():
            return cls.auction_name_to_num(auction)
        elif isinstance(auction, int):
            return auction
        elif auction.isdigit():
            return int(auction)
        raise PydanticCustomError("wrong_auction", "Wrong auction")


async def get_lot_vin_or_lot_id(
    api: "AuctionApiClient", site: "SiteEnum", vin_or_lot_id: str
):
    vin_or_lot = vin_or_lot_id.replace(" ", "").upper()
    if vin_or_lot.isdigit():
        try:
            logger.debug(
                f"Request routed to get by lot_id - {vin_or_lot}",
                extra={"site": site, "vin_or_lot_id": vin_or_lot},
            )
            in_data = LotByIDIn(site=site, lot_id=int(vin_or_lot))
            response = await api.request_with_schema(
                api.GET_LOT_BY_ID_FOR_ALL_TIME, in_data, lot_id=vin_or_lot
            )
        except NotFoundProblem:
            response = None
    else:
        logger.debug(
            f"Request routed to get by vin - {vin_or_lot}",
            extra={"site": site, "vin_or_lot_id": vin_or_lot},
        )
        in_data = LotByVINIn(vin=vin_or_lot, site=site)
        response = await api.request_with_schema(
            api.GET_LOT_BY_VIN_FOR_ALL_TIME, in_data
        )
    if not response:
        in_data = LotByIDIn(site=site, lot_id=int(vin_or_lot))
        response = await api.request_with_schema(
            api.GET_LOT_BY_ID_FOR_CURRENT, in_data, lot_id=vin_or_lot
        )
    return response
