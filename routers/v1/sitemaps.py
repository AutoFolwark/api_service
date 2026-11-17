import re
from collections.abc import Iterator
from dataclasses import dataclass
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
from starlette.concurrency import run_in_threadpool

from config import settings
from core.logger import logger

sitemaps_router = APIRouter()

SITEMAP_SUFFIXES = (".xml", ".xml.gz")
XML_CONTENT_TYPE = "application/xml"
GZIP_CONTENT_TYPE = "application/gzip"
CACHE_CONTROL = "public, max-age=3600"
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
    return XML_CONTENT_TYPE


def _etag_matches(etag: str | None, header: str) -> bool:
    if not etag:
        return False
    if header.strip() == "*":
        return True

    def normalize(value: str) -> str:
        value = value.strip()
        if value.startswith("W/"):
            value = value[2:].strip()
        return value

    current = normalize(etag)
    return any(normalize(part) == current for part in header.split(",") if part.strip())


def _is_not_modified_since(last_modified: datetime, header: str) -> bool:
    try:
        since = parsedate_to_datetime(header)
    except (TypeError, ValueError, IndexError):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    modified = last_modified.astimezone(timezone.utc).replace(microsecond=0)
    return modified <= since.astimezone(timezone.utc).replace(microsecond=0)


def _not_modified(
    etag: str | None,
    last_modified: datetime | None,
    if_none_match: str | None,
    if_modified_since: str | None,
) -> bool:
    # If-None-Match takes precedence over If-Modified-Since (RFC 9110).
    if if_none_match is not None:
        return _etag_matches(etag, if_none_match)
    if if_modified_since is not None and last_modified is not None:
        return _is_not_modified_since(last_modified, if_modified_since)
    return False


@dataclass
class SitemapObject:
    body: Any | None
    etag: str | None
    last_modified: datetime | None
    not_modified: bool
    content_length: int | None


def _open_sitemap(
    key: str,
    if_none_match: str | None,
    if_modified_since: str | None,
) -> SitemapObject | None:
    s3 = _s3_client()
    try:
        head = s3.head_object(Bucket=settings.SITEMAP_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
            return None
        raise

    etag = head.get("ETag")
    last_modified = head.get("LastModified")
    content_length = head.get("ContentLength")
    if _not_modified(etag, last_modified, if_none_match, if_modified_since):
        return SitemapObject(
            body=None,
            etag=etag,
            last_modified=last_modified,
            not_modified=True,
            content_length=content_length,
        )

    obj = s3.get_object(Bucket=settings.SITEMAP_BUCKET, Key=key)
    return SitemapObject(
        body=obj["Body"],
        etag=etag,
        last_modified=last_modified,
        not_modified=False,
        content_length=content_length,
    )


def _iter_body(body: Any) -> Iterator[bytes]:
    try:
        yield from body.iter_chunks(chunk_size=256 * 1024)
    finally:
        body.close()


def _response_headers(opened: SitemapObject, include_length: bool) -> dict[str, str]:
    headers = {"Cache-Control": CACHE_CONTROL}
    if opened.etag:
        headers["ETag"] = opened.etag
    if opened.last_modified is not None:
        headers["Last-Modified"] = format_datetime(opened.last_modified, usegmt=True)
    if include_length and opened.content_length is not None:
        headers["Content-Length"] = str(opened.content_length)
    return headers


@sitemaps_router.get(
    "/{path:path}",
    description="Stream a generated sitemap from S3, e.g. sitemap-index.xml",
)
async def get_sitemap(path: str, request: Request):
    if not _is_valid_sitemap_path(path):
        raise NotFoundProblem(detail="Sitemap not found")

    try:
        opened = await run_in_threadpool(
            _open_sitemap,
            f"{settings.SITEMAP_PREFIX}{path}",
            request.headers.get("if-none-match"),
            request.headers.get("if-modified-since"),
        )
    except Exception:
        logger.exception("Failed to read sitemap", extra={"path": path})
        raise

    if opened is None:
        raise NotFoundProblem(detail="Sitemap not found")
    if opened.not_modified:
        return Response(status_code=304, headers=_response_headers(opened, False))

    return StreamingResponse(
        _iter_body(opened.body),
        media_type=_content_type(path),
        headers=_response_headers(opened, True),
    )
