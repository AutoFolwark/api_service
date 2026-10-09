import re
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from rfc9457 import NotFoundProblem
from starlette.concurrency import run_in_threadpool

from config import settings

sitemaps_router = APIRouter()

SITEMAP_SUFFIXES = (".xml", ".xml.gz")
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
    return all(segment not in (".", "..") and _PATH_SEGMENT.fullmatch(segment) for segment in segments)


def _presigned_sitemap_url(key: str) -> str | None:
    s3 = _s3_client()
    try:
        s3.head_object(Bucket=settings.SITEMAP_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
            return None
        raise
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.SITEMAP_BUCKET, "Key": key},
        ExpiresIn=settings.SITEMAP_URL_TTL_SECONDS,
    )


@sitemaps_router.get(
    "/{path:path}",
    response_class=RedirectResponse,
    status_code=302,
    description="Redirect to a short-lived S3 URL of a generated sitemap, e.g. sitemap-index.xml",
)
async def get_sitemap(path: str):
    if not _is_valid_sitemap_path(path):
        raise NotFoundProblem(detail="Sitemap not found")

    url = await run_in_threadpool(_presigned_sitemap_url, f"{settings.SITEMAP_PREFIX}{path}")
    if url is None:
        raise NotFoundProblem(detail="Sitemap not found")

    # Presigned URLs expire, so neither proxies nor crawlers may keep this redirect.
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
