import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Type, TypeVar

import httpx
from pydantic import BaseModel
from rfc9457 import BadRequestProblem, NotFoundProblem

from auction_api.types.common import SiteEnum
from core.logger import log_async_execution_time, logger, truncate_log_value

from .types import BaseClientIn

if TYPE_CHECKING:
    from auction_api.api import EndpointSchema


T = TypeVar("T", bound=BaseModel)
MAX_ERROR_BODY_LOG_CHARS = 1000
REQUEST_ATTEMPTS = 3
REQUEST_RETRY_DELAY_SECONDS = 1.0
RETRYABLE_REQUEST_ERRORS = (
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.DecodingError,
)


class BaseClient(ABC):
    def __init__(self, data: BaseClientIn):
        self.api_key = data.api_key
        self.header_name = data.header_name
        self.base_url = str(data.base_url)
        self._http_client: httpx.AsyncClient | None = None

    def _build_url(self, url: str) -> str:
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    @staticmethod
    def _flatten_query_params(payload: dict) -> list[tuple[str, Any]]:
        """Repeat list values as separate query params for the auction API."""
        params: list[tuple[str, Any]] = []
        for key, value in payload.items():
            if isinstance(value, (list, tuple)):
                params.extend((key, item) for item in value)
            else:
                params.append((key, value))
        return params

    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {self.header_name: self.api_key}
        client = self._http_client
        close_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=10)
        try:
            for attempt in range(1, REQUEST_ATTEMPTS + 1):
                try:
                    response = await client.request(
                        method, url, headers=headers, **kwargs
                    )
                except RETRYABLE_REQUEST_ERRORS as exc:
                    await self._handle_retryable_request_error(
                        exc, method, url, attempt, kwargs
                    )
                    continue
                except httpx.HTTPError as exc:
                    detail = self._request_failure_detail(
                        method, url, attempt, kwargs, exc=exc, retrying=False
                    )
                    logger.error(detail)
                    raise BadRequestProblem(detail=detail) from exc

                if response.is_server_error and attempt < REQUEST_ATTEMPTS:
                    detail = self._request_failure_detail(
                        method,
                        url,
                        attempt,
                        kwargs,
                        response=response,
                        retrying=True,
                    )
                    logger.warning(detail)
                    await response.aclose()
                    await asyncio.sleep(REQUEST_RETRY_DELAY_SECONDS * attempt)
                    continue
                return response
            raise RuntimeError(f"Request retry loop exhausted for {method} {url}")
        finally:
            if close_client:
                await client.aclose()

    async def _handle_retryable_request_error(
        self,
        exc: httpx.HTTPError,
        method: str,
        url: str,
        attempt: int,
        kwargs: dict,
    ) -> None:
        retrying = attempt < REQUEST_ATTEMPTS
        detail = self._request_failure_detail(
            method, url, attempt, kwargs, exc=exc, retrying=retrying
        )
        if not retrying:
            logger.error(detail)
            raise BadRequestProblem(detail=detail) from exc
        logger.warning(detail)
        await asyncio.sleep(REQUEST_RETRY_DELAY_SECONDS * attempt)

    def _request_failure_detail(
        self,
        method: str,
        url: str,
        attempt: int,
        kwargs: dict,
        exc: httpx.HTTPError | None = None,
        response: httpx.Response | None = None,
        retrying: bool = False,
    ) -> str:
        action = "retrying" if retrying else "not retrying"
        reason = f"{type(exc).__name__}: {exc}" if exc is not None else ""
        if response is not None:
            preview = (response.content or b"")[:MAX_ERROR_BODY_LOG_CHARS].decode(
                "utf-8", errors="replace"
            )
            content_type = response.headers.get("content-type", "")
            reason = (
                f"HTTP {response.status_code} content-type={content_type!r} "
                f"body={preview!r}"
            )
        return (
            f"Request to API failed on {method} {url} "
            f"attempt {attempt}/{REQUEST_ATTEMPTS} ({action}): {reason}; "
            f"request={truncate_log_value(kwargs)}"
        )

    @log_async_execution_time("Request to external API")
    async def request_with_schema(
        self, schema: "EndpointSchema", data: BaseModel, **kwargs
    ) -> Type[T]:
        url = self._build_url(schema.endpoint.format(**kwargs))

        payload = data.model_dump(exclude_none=True, mode="json")

        site_val = payload.get("site")
        if site_val is not None:
            normalized = str(site_val).lower()
            if normalized in {SiteEnum.ALL_NUM, SiteEnum.ALL}:
                payload["site"] = [1, 2]

        logger.debug(f"Request payload: {truncate_log_value(payload)}, url: {url}")

        if schema.method == "GET":
            response = await self._make_request(
                "GET", url, params=self._flatten_query_params(payload)
            )
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
            response_preview = (response.content or b"")[
                :MAX_ERROR_BODY_LOG_CHARS
            ].decode("utf-8", errors="replace")
            logger.warning(
                f"Request to API returned status {response.status_code} for {url}; "
                f"content-type={response.headers.get('content-type', '')!r}; "
                f"body={response_preview!r}",
                extra={
                    "data": {
                        "url": url,
                        "payload": truncate_log_value(payload),
                        "status_code": response.status_code,
                        "response_content_length": len(response.content or b""),
                        "response_preview": response_preview,
                    }
                },
            )
            raise NotFoundProblem("Lot not found")

        if response_data is None:
            logger.error(
                "Expected JSON response, got empty or invalid JSON",
                extra={
                    "data": {
                        "url": url,
                        "status_code": response.status_code,
                        "payload": truncate_log_value(payload),
                        "response_content_length": len(response.content or b""),
                        "response_preview": (response.content or b"")[
                            :MAX_ERROR_BODY_LOG_CHARS
                        ].decode("utf-8", errors="replace"),
                    }
                },
            )
            raise BadRequestProblem(detail="Invalid JSON response from API")

        return self.process_response(response_data, schema)

    @abstractmethod
    def process_response(
        self, response_data: dict | list, schema: "EndpointSchema"
    ) -> Type[T]: ...

    def _safe_json(self, response: httpx.Response) -> Any | None:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None
