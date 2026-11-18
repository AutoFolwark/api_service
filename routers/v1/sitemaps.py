import re
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from rfc9457 import NotFoundProblem
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from config import settings
from core.logger import logger

sitemaps_router = APIRouter()

SITEMAP_SUFFIXES = (".xml", ".xml.gz")
XML_MEDIA_TYPE = "application/xml; charset=utf-8"
GZIP_CONTENT_TYPE = "application/gzip"
CACHE_CONTROL = "public, max-age=300"
CHUNK_SIZE = 64 * 1024
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
_MISSING_OBJECT_CODES = {"403", "404", "NoSuchKey", "NotFound", "AccessDenied"}


@lru_cache
def _s3_client() -> Any:
    region = settings.SITEMAP_BUCKET_REGION
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def _is_valid_sitemap_path(path: str) -> bool:
    if not path.endswith(SITEMAP_SUFFIXES):
        return False
    segments = path.split("/")
    return all(
        segment not in (".", "..") and _PATH_SEGMENT.fullmatch(segment)
        for segment in segments
    )


def _content_type(path: str) -> str:
    if path.endswith(".gz"):
        return GZIP_CONTENT_TYPE
    return XML_MEDIA_TYPE


def _is_missing(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES


def _is_not_modified(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return error.get("Code") in {"304", "NotModified"} or status == 304


def _conditional_params(request: Request) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if match := request.headers.get("if-none-match"):
        params["IfNoneMatch"] = match
    if since := request.headers.get("if-modified-since"):
        try:
            parsed = parsedate_to_datetime(since)
        except (TypeError, ValueError, IndexError, OverflowError):
            parsed = None
        if parsed is not None:
            params["IfModifiedSince"] = parsed
    return params


def _http_date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return format_datetime(value, usegmt=True)


def _response_headers(head: dict[str, Any]) -> dict[str, str]:
    headers = {"Cache-Control": CACHE_CONTROL}
    if etag := head.get("ETag"):
        headers["ETag"] = etag
    if (last_modified := head.get("LastModified")) is not None:
        headers["Last-Modified"] = _http_date(last_modified)
    if (content_length := head.get("ContentLength")) is not None:
        headers["Content-Length"] = str(content_length)
    return headers


def _not_modified_headers(exc: ClientError) -> dict[str, str]:
    headers = {"Cache-Control": CACHE_CONTROL}
    http_headers = exc.response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    if etag := http_headers.get("etag"):
        headers["ETag"] = etag
    if last_modified := http_headers.get("last-modified"):
        headers["Last-Modified"] = last_modified
    return headers


def _head_object(
    key: str, conditional: dict[str, Any]
) -> dict[str, Any] | Response | None:
    try:
        return _s3_client().head_object(
            Bucket=settings.SITEMAP_BUCKET, Key=key, **conditional
        )
    except ClientError as exc:
        if _is_not_modified(exc):
            return Response(status_code=304, headers=_not_modified_headers(exc))
        if _is_missing(exc):
            return None
        raise


def _open_object(
    key: str, conditional: dict[str, Any]
) -> dict[str, Any] | Response | None:
    try:
        return _s3_client().get_object(
            Bucket=settings.SITEMAP_BUCKET, Key=key, **conditional
        )
    except ClientError as exc:
        if _is_not_modified(exc):
            return Response(status_code=304, headers=_not_modified_headers(exc))
        if _is_missing(exc):
            return None
        raise


async def _stream_body(body: Any):
    try:
        async for chunk in iterate_in_threadpool(body.iter_chunks(CHUNK_SIZE)):
            yield chunk
    finally:
        close = getattr(body, "close", None)
        if close is not None:
            await run_in_threadpool(close)


@sitemaps_router.api_route(
    "/{path:path}",
    methods=["GET", "HEAD"],
    description="Serve a generated sitemap, e.g. sitemap.xml",
)
async def get_sitemap(path: str, request: Request):
    if not _is_valid_sitemap_path(path):
        raise NotFoundProblem(detail="Sitemap not found")

    key = f"{settings.SITEMAP_PREFIX}{path}"
    conditional = _conditional_params(request)
    media_type = _content_type(path)
    try:
        if request.method == "HEAD":
            result = await run_in_threadpool(_head_object, key, conditional)
        else:
            result = await run_in_threadpool(_open_object, key, conditional)
    except Exception:
        logger.exception("Failed to read sitemap", extra={"path": path})
        raise

    if result is None:
        raise NotFoundProblem(detail="Sitemap not found")
    if isinstance(result, Response):
        return result
    if request.method == "HEAD":
        return Response(
            status_code=200, media_type=media_type, headers=_response_headers(result)
        )
    return StreamingResponse(
        _stream_body(result["Body"]),
        status_code=200,
        media_type=media_type,
        headers=_response_headers(result),
    )
