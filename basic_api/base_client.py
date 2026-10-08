from abc import abstractmethod, ABC
from typing import List, TYPE_CHECKING, Type, TypeVar, Any

from pydantic import BaseModel
from rfc9457 import BadRequestProblem, NotFoundProblem

from auction_api.types.common import SiteEnum
from core.logger import logger, log_async_execution_time, truncate_log_value
from .types import BaseClientIn
import httpx

if TYPE_CHECKING:
    from auction_api.api import EndpointSchema


T = TypeVar("T", bound=BaseModel)
MAX_ERROR_BODY_LOG_CHARS = 1000

class BaseClient(ABC):
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)
        self._http_client: httpx.AsyncClient | None = None

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        client = self._http_client
        close_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=10)
        try:
            return await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as e:
            logger.error(f"Request to API Failed", exc_info=e, extra={
                'data': {
                    'url': url,
                    'headers': truncate_log_value(headers),
                    'kwargs': truncate_log_value(kwargs),
                    'error': truncate_log_value(str(e))
                }
            })
            raise BadRequestProblem(detail='Request to API Failed') from e
        finally:
            if close_client:
                await client.aclose()

    @log_async_execution_time('Request to external API')
    async def request_with_schema(self, schema: "EndpointSchema", data: BaseModel, **kwargs) -> Type[T]:
        url = self._build_url(schema.endpoint.format(**kwargs))

        payload = data.model_dump(exclude_none=True, mode='json')

        site_val = payload.get('site')
        if site_val is not None:
            normalized = str(site_val).lower()
            if normalized in {SiteEnum.ALL_NUM, SiteEnum.ALL}:
                payload['site'] = [1, 2]

        logger.debug(f"Request payload: {truncate_log_value(payload)}, url: {url}")

        if schema.method == "GET":
            response = await self._make_request("GET", url, params=payload)
        elif schema.method == "POST":
            response = await self._make_request("POST", url, json=payload)
        else:
            logger.error(f"Unsupported method: {schema.method}")
            raise ValueError(f"Unsupported method: {schema.method}")

        response_data = self._safe_json(response)
        logger.debug(
            "Response received",
            extra={
                "data": {
                    "status_code": response.status_code,
                    "url": url,
                    "has_json": response_data is not None,
                    "content_length": len(response.content or b""),
                }
            },
        )

        if response.status_code != httpx.codes.OK:
            logger.warning(f"Request failed, lot not found or smth", extra={
                'data': {
                    'url': url,
                    'payload': truncate_log_value(payload),
                    'status_code': response.status_code,
                    'response_content_length': len(response.content or b""),
                    'response_preview': (response.content or b"")[:MAX_ERROR_BODY_LOG_CHARS].decode(
                        "utf-8", errors="replace"
                    ),
                }
            })
            raise NotFoundProblem('Lot not found')

        if response_data is None:
            logger.error("Expected JSON response, got empty or invalid JSON", extra={
                "data": {
                    "url": url,
                    "status_code": response.status_code,
                    "payload": truncate_log_value(payload),
                    "response_content_length": len(response.content or b""),
                    "response_preview": (response.content or b"")[:MAX_ERROR_BODY_LOG_CHARS].decode(
                        "utf-8", errors="replace"
                    ),
                }
            })
            raise BadRequestProblem(detail='Invalid JSON response from API')

        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(self, response_data: dict | list, schema: "EndpointSchema") -> Type[T]:
        ...

    def _safe_json(self, response: httpx.Response) -> Any | None:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

