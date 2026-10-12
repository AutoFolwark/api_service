import json
import traceback
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

import grpc
import redis.asyncio as redis
from rfc9457 import BadRequestProblem, NotFoundProblem

from auction_api.api import AuctionApiClient, EndpointSchema
from auction_api.types.search import CurrentSearchParams, SellerTypeEnum, SiteEnum
from auction_api.utils import get_lot_vin_or_lot_id
from config import settings
from core.logger import logger
from request_schemas.lot import GetAveragedPriceIn, LotByIDIn
from rpc_server.cache import CacheKeyBuilder, RedisCache
from rpc_server.gen.python.auction.v1 import lot_pb2, lot_pb2_grpc

T = TypeVar("T")


def handle_grpc_errors(method_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, request, context):
            try:
                return await func(self, request, context)
            except NotFoundProblem as e:
                self._log_error("warning", e, method=method_name)
                self._set_not_found_error(context)
                return self._get_empty_response(func.__name__)
            except BadRequestProblem as e:
                self._log_error("warning", e, method=method_name)
                self._set_invalid_argument_error(context, "Invalid arguments")
                return self._get_empty_response(func.__name__)
            except ValueError as e:
                self._log_error("warning", e, method=method_name)
                self._set_invalid_argument_error(context, f"Invalid parameters: {e}")
                return self._get_empty_response(func.__name__)
            except Exception as e:
                self._log_error("error", e, method=method_name)
                self._set_internal_error(context)
                return self._get_empty_response(func.__name__)

        return wrapper

    return decorator


class CacheManager:
    def __init__(self, cache: Optional[RedisCache]):
        self.cache = cache

    async def get_cached_data(self, key: str) -> Optional[Any]:
        if not self.cache:
            return None

        cached_data = await self.cache.get(key)
        if cached_data:
            logger.debug(f"Cache hit for key: {key}")

            if isinstance(cached_data, str):
                try:
                    return json.loads(cached_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode cached data: {e}")
                    return None
            return cached_data

        logger.debug(f"Cache miss for key: {key}")
        return None

    async def set_cache_data(self, key: str, value: Any, ttl: int) -> None:
        if self.cache and value is not None:
            await self.cache.set(key, value, ttl)
            logger.debug(f"Cached data for key: {key} with TTL: {ttl}s")


class BaseRpcService:
    def __init__(self):
        self.api = AuctionApiClient()
        self.redis_client = None
        self.cache = None
        self.cache_manager = None
        self._init_redis()

    def _init_redis(self):
        try:
            if settings.REDIS_URL:
                self.redis_client = redis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    retry_on_error=[ConnectionError, TimeoutError],
                    max_connections=50,
                )
                self.cache = RedisCache(self.redis_client)
                self.cache_manager = CacheManager(self.cache)
                logger.info("Redis cache initialized successfully")
            else:
                logger.warning("Redis URL not configured, caching disabled")
                self.cache_manager = CacheManager(None)
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self.cache = None
            self.cache_manager = CacheManager(None)

    @staticmethod
    def _parse_site_enum(site: str) -> Optional[SiteEnum]:
        return SiteEnum(site.lower()) if site else None

    @staticmethod
    def _set_not_found_error(context, message: str = "Not found"):
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(message)

    @staticmethod
    def _set_invalid_argument_error(context, message: str):
        context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
        context.set_details(message)

    @staticmethod
    def _set_internal_error(context, message: str = "Internal server error"):
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(message)

    @staticmethod
    def _log_request(method_name: str, **kwargs):
        logger.debug(f"Request {method_name} using gRPC", extra=kwargs)

    @staticmethod
    def _log_error(error_type: str, error: Exception, **kwargs):
        logger_method = logger.error if error_type == "error" else logger.warning
        logger_method(
            f"{error_type} in {kwargs.get('method', 'unknown method')}",
            extra={"error": str(error), "traceback": traceback.format_exc(), **kwargs},
        )

    def _get_empty_response(self, method_name: str):
        response_mapping = {
            "GetLot": lot_pb2.GetLotResponse,
            "GetCurrentBid": lot_pb2.GetCurrentBidResponse,
            "GetLotByVinOrLot": lot_pb2.GetLotByVinOrLotResponse,
            "GetSaleHistory": lot_pb2.GetSaleHistoryResponse,
            "GetCurrentLotsByFilters": lot_pb2.GetCurrentLotsByFiltersResponse,
            "GetAveragePriceByMakeModel": lot_pb2.GetAveragePriceByMakeModelResponse,
        }
        return response_mapping.get(method_name, lambda: None)()

    async def close(self):
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")


class LotRpc(BaseRpcService, lot_pb2_grpc.LotServiceServicer):
    TTL_LOT = 10 * 60
    TTL_CURRENT_BID = 10 * 60
    TTL_SALE_HISTORY = 60 * 60
    TTL_VIN_LOOKUP = 30 * 60
    TTL_CURRENT_LOTS = 60 * 60
    TTL_AVERAGE_PRICE = 60 * 360

    def _create_lot_by_id_data(self, lot_id: int, site: str) -> LotByIDIn:
        site_enum = self._parse_site_enum(site)
        return LotByIDIn(lot_id=lot_id, site=site_enum)

    def _convert_to_lot_proto(self, lot_data) -> lot_pb2.Lot:
        if hasattr(lot_data, "model_dump"):
            lot_dict = lot_data.model_dump(mode="json", exclude_none=True)
        else:
            lot_dict = lot_data
        return lot_pb2.Lot(**lot_dict)

    def _process_lot_response(self, lot, response_class):
        if isinstance(lot, list):
            logger.debug(f"Received list of lots, count: {len(lot)}")
            lots = [self._convert_to_lot_proto(item) for item in lot]
            return response_class(lot=lots)

        response_lot = self._convert_to_lot_proto(lot)
        return response_class(lot=[response_lot])

    def _prepare_cache_data(self, data: Any) -> Any:
        if isinstance(data, list):
            return [
                item.model_dump(mode="json", exclude_none=True)
                if hasattr(item, "model_dump")
                else item
                for item in data
            ]
        elif hasattr(data, "model_dump"):
            return data.model_dump(mode="json", exclude_none=True)
        return data

    async def _execute_with_cache(
        self,
        cache_key: str,
        api_method: EndpointSchema,
        api_params: Any,
        ttl: int,
        transform_func: Optional[Callable] = None,
    ) -> Any:
        cached_data = await self.cache_manager.get_cached_data(cache_key)
        if cached_data:
            return transform_func(cached_data) if transform_func else cached_data

        result = await self.api.request_with_schema(api_method, api_params)

        if result:
            cache_data = self._prepare_cache_data(result)
            await self.cache_manager.set_cache_data(cache_key, cache_data, ttl)

        return result

    def _clean_request_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in data.items() if v is not None and v != 0 and v != ""}

    def transform_lots_to_proto(
        self, data: dict
    ) -> lot_pb2.GetCurrentLotsByFiltersResponse:
        lots = [self._convert_to_lot_proto(lot) for lot in data.get("data", [])]

        pagination = lot_pb2.Pagination(
            page=data.get("page"),
            size=data.get("size"),
            pages=data.get("pages"),
            count=data.get("count"),
        )

        return lot_pb2.GetCurrentLotsByFiltersResponse(lot=lots, pagination=pagination)

    @classmethod
    def transform_average_price_to_proto(
        cls, data: dict
    ) -> lot_pb2.GetAveragePriceByMakeModelResponse:
        stats_proto_items = [
            lot_pb2.StatsItem(
                total=item.get("total"),
                min=item.get("min"),
                max=item.get("max"),
                count=item.get("count"),
            )
            for item in data.values()
        ]

        return lot_pb2.GetAveragePriceByMakeModelResponse(stats=stats_proto_items)

    @handle_grpc_errors("GetLot")
    async def GetLot(self, request: lot_pb2.GetLotRequest, context):
        if not request.lot_id:
            self._set_invalid_argument_error(context, "Lot ID is required")
            return lot_pb2.GetLotResponse()

        self._log_request("get lot by id", lot_id=request.lot_id, site=request.site)

        cache_key = CacheKeyBuilder.lot_by_id(request.lot_id, request.site)
        data = self._create_lot_by_id_data(request.lot_id, request.site)

        lot = await self._execute_with_cache(
            cache_key=cache_key,
            api_method=AuctionApiClient.GET_LOT_BY_ID_FOR_ALL_TIME,
            api_params=data,
            ttl=self.TTL_LOT,
        )

        if not lot:
            self._set_not_found_error(context, "Lot not found")
            return lot_pb2.GetLotResponse()

        return self._process_lot_response(lot, lot_pb2.GetLotResponse)

    @handle_grpc_errors("GetCurrentBid")
    async def GetCurrentBid(self, request: lot_pb2.GetCurrentBidRequest, context):
        cache_key = CacheKeyBuilder.current_bid(request.lot_id, request.site)
        data = self._create_lot_by_id_data(request.lot_id, request.site)

        current_bid = await self._execute_with_cache(
            cache_key=cache_key,
            api_method=self.api.GET_CURRENT_BID_FOR_LOT,
            api_params=data,
            ttl=self.TTL_CURRENT_BID,
        )

        if not current_bid:
            self._set_not_found_error(context)
            return lot_pb2.GetCurrentBidResponse()

        bid_data = (
            current_bid.model_dump(mode="json", exclude_none=True)
            if hasattr(current_bid, "model_dump")
            else current_bid
        )

        return lot_pb2.GetCurrentBidResponse(current_bid=lot_pb2.CurrentBid(**bid_data))

    @handle_grpc_errors("GetLotByVinOrLot")
    async def GetLotByVinOrLot(self, request: lot_pb2.GetLotByVinOrLotRequest, context):
        vin_or_lot = request.vin_or_lot_id.replace(" ", "").upper()
        self._log_request(
            "get lot by vin or lot id", vin_or_lot_id=request.vin_or_lot_id
        )

        cache_key = CacheKeyBuilder.lot_by_vin_or_id(vin_or_lot, request.site)

        cached_lot = await self.cache_manager.get_cached_data(cache_key)
        if cached_lot:
            return self._process_lot_response(
                cached_lot, lot_pb2.GetLotByVinOrLotResponse
            )

        site_enum = self._parse_site_enum(request.site)
        lot = await get_lot_vin_or_lot_id(self.api, site_enum, vin_or_lot)

        if not lot:
            self._set_not_found_error(context)
            return lot_pb2.GetLotByVinOrLotResponse()

        cache_data = self._prepare_cache_data(lot if isinstance(lot, list) else [lot])
        await self.cache_manager.set_cache_data(
            cache_key, cache_data, self.TTL_VIN_LOOKUP
        )

        return self._process_lot_response(lot, lot_pb2.GetLotByVinOrLotResponse)

    @handle_grpc_errors("GetSaleHistory")
    async def GetSaleHistory(self, request: lot_pb2.GetSaleHistoryRequest, context):
        cache_key = CacheKeyBuilder.sale_history(request.lot_id, request.site)
        data = self._create_lot_by_id_data(request.lot_id, request.site)

        lot = await self._execute_with_cache(
            cache_key=cache_key,
            api_method=AuctionApiClient.GET_LOT_HISTORY_BY_ID,
            api_params=data,
            ttl=self.TTL_SALE_HISTORY,
        )

        if not lot:
            self._set_not_found_error(context)
            return lot_pb2.GetSaleHistoryResponse()

        lot_data = (
            lot.model_dump(mode="json", exclude_none=True)
            if hasattr(lot, "model_dump")
            else lot
        )

        return lot_pb2.GetSaleHistoryResponse(lot=[lot_pb2.Lot(**lot_data)])

    @handle_grpc_errors("GetCurrentLotsByFilters")
    async def GetCurrentLotsByFilters(
        self, request: lot_pb2.GetCurrentLotsByFiltersRequest, context
    ):
        data = {
            "page": request.page,
            "size": request.size,
            "site": self._parse_site_enum(request.site) if request.site else None,
            "make": request.make,
            "model": request.model,
            "year_from": request.year_from,
            "year_to": request.year_to,
            "vehicle_type": request.vehicle_type,
            "transmission": [request.transmission] if request.transmission else None,
            "odometer_min": request.odometer_min,
            "document": [request.document] if request.document else None,
            "odometer_max": request.odometer_max,
            "drive": [request.drive] if request.drive else None,
            "status": [request.status] if request.status else None,
            "auction_date_from": request.auction_date_from
            if request.auction_date_from
            else None,
            "auction_date_to": request.auction_date_to
            if request.auction_date_to
            else None,
        }

        data = self._clean_request_data(data)
        cache_key = CacheKeyBuilder.current_lots(**data)

        cached_lots = await self.cache_manager.get_cached_data(cache_key)
        if cached_lots:
            return self.transform_lots_to_proto(cached_lots)

        lots = await self.api.request_with_schema(
            AuctionApiClient.GET_CURRENT_LOTS,
            CurrentSearchParams(**data, seller_type=SellerTypeEnum.INSURANCE),
        )

        lots_data = lots.model_dump(mode="json", exclude_none=True)
        await self.cache_manager.set_cache_data(
            cache_key, lots_data, self.TTL_CURRENT_LOTS
        )

        return self.transform_lots_to_proto(lots_data)

    @handle_grpc_errors("GetAveragePriceByMakeModel")
    async def GetAveragePriceByMakeModel(
        self, request: lot_pb2.GetAveragePriceByMakeModelRequest, context
    ) -> lot_pb2.GetAveragePriceByMakeModelResponse:
        data = {
            "make": request.make,
            "model": request.model,
            "year_from": request.year_from,
            "year_to": request.year_to,
            "period": request.period,
        }

        data = self._clean_request_data(data)
        cache_key = CacheKeyBuilder.average_price(**data)

        cached_price = await self.cache_manager.get_cached_data(cache_key)
        if cached_price:
            return self.transform_average_price_to_proto(cached_price)

        prices = await self.api.request_with_schema(
            AuctionApiClient.GET_AVERAGES_FOR_LOT, GetAveragedPriceIn(**data)
        )

        prices_data = prices.model_dump(mode="json", exclude_none=True)
        await self.cache_manager.set_cache_data(
            cache_key, prices_data, self.TTL_AVERAGE_PRICE
        )

        return self.transform_average_price_to_proto(prices_data)
