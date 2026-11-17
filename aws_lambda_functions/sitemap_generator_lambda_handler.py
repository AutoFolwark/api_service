import asyncio
import gzip
import io
import time
from collections.abc import AsyncIterator, Awaitable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import IO, Any
from xml.sax.saxutils import escape

import boto3
from loguru import logger
from sqlalchemy import Row, select

from config import settings
from database.db.session import AsyncSessionLocal, engine_async
from database.models.saved_lots import SavedLots
from services.lot_urls import lot_path

MAX_URLS_PER_SITEMAP = 50_000
# Google's limit is 50MB uncompressed. Roll over early so the closing tag fits.
MAX_UNCOMPRESSED_BYTES = 45 * 1024 * 1024
FETCH_BATCH = 20_000

STATIC_SITEMAP_FOLDER = "static_sitemaps/"
STATIC_SITEMAP_SUFFIXES = (".xml", ".xml.gz")
INDEX_NAME = "sitemap-index.xml"
S3_DELETE_BATCH = 1000
MAX_CONCURRENT_UPLOADS = 4
PROGRESS_LOG_EVERY = 100_000

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'
XML_CONTENT_TYPE = "application/xml"
GZIP_CONTENT_TYPE = "application/gzip"
URLSET_HEADER = f'{XML_DECLARATION}<urlset xmlns="{SITEMAP_NS}">\n'.encode("utf-8")
URLSET_FOOTER = b"</urlset>\n"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _w3c_datetime(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _effective_lastmod(value: datetime | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    utc = _as_utc(value)
    return now if utc > now else utc


def _sitemap_key(name: str) -> str:
    return f"{settings.SITEMAP_PREFIX}{name}"


def _sitemap_public_url(name: str) -> str:
    return f"{settings.SITEMAP_PUBLIC_BASE_URL.rstrip('/')}/{name}"


def _mb(size: int) -> float:
    return size / (1024 * 1024)


async def _stream_lot_batches() -> AsyncIterator[Sequence[Row]]:
    statement = (
        select(
            SavedLots.base_site,
            SavedLots.site,
            SavedLots.lot_id,
            SavedLots.year,
            SavedLots.make,
            SavedLots.model,
            SavedLots.vin,
            SavedLots.updated_at,
        )
        .where(SavedLots.is_deleted.is_(False))
        .execution_options(yield_per=FETCH_BATCH)
    )
    async with AsyncSessionLocal() as session:
        result = await session.stream(statement)
        async for batch in result.partitions():
            yield batch


@dataclass
class SitemapChunk:
    name: str
    data: io.BytesIO | None
    url_count: int = 0
    size: int = 0
    uncompressed_size: int = 0
    lastmod: datetime | None = None


class SitemapChunkWriter:
    def __init__(
        self,
        lang: str,
        max_urls: int = MAX_URLS_PER_SITEMAP,
        max_bytes: int = MAX_UNCOMPRESSED_BYTES,
    ):
        self.lang = lang
        self.max_urls = max_urls
        self.max_bytes = max_bytes
        self.chunks: list[SitemapChunk] = []
        self._current: SitemapChunk | None = None
        self._gzip: gzip.GzipFile | None = None

    def add(self, entry: bytes, lastmod: datetime | None) -> SitemapChunk | None:
        """Returns the previous chunk once it is full and ready to upload."""
        finished = None
        chunk = self._current
        if chunk is not None and (
            chunk.url_count >= self.max_urls
            or chunk.uncompressed_size + len(entry) > self.max_bytes
        ):
            finished = self._close_current()
            chunk = None
        if chunk is None:
            chunk = self._open_next()

        assert self._gzip is not None
        self._gzip.write(entry)
        chunk.url_count += 1
        chunk.uncompressed_size += len(entry)
        if lastmod is not None and (chunk.lastmod is None or lastmod > chunk.lastmod):
            chunk.lastmod = lastmod
        return finished

    def finish(self) -> SitemapChunk | None:
        return self._close_current()

    def _open_next(self) -> SitemapChunk:
        name = f"sitemap-lots-{self.lang}-{len(self.chunks) + 1}.xml.gz"
        data = io.BytesIO()
        self._gzip = gzip.GzipFile(fileobj=data, mode="wb", mtime=0)
        self._gzip.write(URLSET_HEADER)
        chunk = SitemapChunk(name=name, data=data, uncompressed_size=len(URLSET_HEADER))
        self._current = chunk
        self.chunks.append(chunk)
        return chunk

    def _close_current(self) -> SitemapChunk | None:
        chunk = self._current
        data = None if chunk is None else chunk.data
        if chunk is None or data is None or self._gzip is None:
            return None
        self._gzip.write(URLSET_FOOTER)
        chunk.uncompressed_size += len(URLSET_FOOTER)
        self._gzip.close()
        self._gzip = None
        chunk.size = data.tell()
        data.seek(0)
        self._current = None
        return chunk


def _content_type(name: str) -> str:
    if name.endswith(".gz"):
        return GZIP_CONTENT_TYPE
    return XML_CONTENT_TYPE


def _upload_fileobj(s3: Any, name: str, fileobj: IO[bytes]) -> None:
    s3.upload_fileobj(
        fileobj,
        settings.SITEMAP_BUCKET,
        _sitemap_key(name),
        ExtraArgs={"ContentType": _content_type(name)},
    )


class ChunkUploader:
    def __init__(self, s3: Any):
        self.s3 = s3
        self.uploaded: list[SitemapChunk] = []
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
        self._tasks: set[asyncio.Task] = set()

    async def submit(self, chunk: SitemapChunk) -> None:
        self._raise_failed()
        await self._slots.acquire()
        task = asyncio.create_task(self._upload(chunk), name=f"upload-{chunk.name}")
        self._tasks.add(task)

    async def wait(self) -> None:
        await asyncio.gather(*self._tasks)
        self._tasks.clear()

    async def abort(self) -> None:
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _upload(self, chunk: SitemapChunk) -> None:
        try:
            await asyncio.to_thread(_upload_fileobj, self.s3, chunk.name, chunk.data)
            self.uploaded.append(chunk)
        finally:
            chunk.data = None
            self._slots.release()

    def _raise_failed(self) -> None:
        for task in [task for task in self._tasks if task.done()]:
            self._tasks.discard(task)
            task.result()


class BuildTimings:
    def __init__(self):
        self.started_at = time.perf_counter()
        self.db_seconds = 0.0
        self.upload_wait_seconds = 0.0

    async def track_upload_wait(self, awaitable: Awaitable[None]) -> None:
        started_at = time.perf_counter()
        await awaitable
        self.upload_wait_seconds += time.perf_counter() - started_at

    def log_progress(
        self, lot_count: int, uploaded_count: int, final: bool = False
    ) -> None:
        elapsed = time.perf_counter() - self.started_at
        logger.info(
            "{} {} lots ({:.0f} lots/s, {} files uploaded) in {:.1f}s: "
            "db {:.1f}s, build {:.1f}s, waiting for uploads {:.1f}s",
            "Finished" if final else "Added",
            lot_count,
            lot_count / elapsed if elapsed else 0,
            uploaded_count,
            elapsed,
            self.db_seconds,
            elapsed - self.db_seconds - self.upload_wait_seconds,
            self.upload_wait_seconds,
        )


def _lot_entry(row: Row, now: datetime) -> tuple[str, datetime | None] | None:
    path = lot_path(
        lot_id=row.lot_id,
        base_site=row.base_site,
        site=row.site,
        year=row.year,
        make=row.make,
        model=row.model,
        vin=row.vin,
    )
    if path is None:
        return None
    lastmod = _effective_lastmod(row.updated_at, now)
    entry = f"{escape(path)}</loc>"
    if lastmod is not None:
        entry += f"<lastmod>{_w3c_datetime(lastmod)}</lastmod>"
    return entry, lastmod


async def _build_and_upload_lot_sitemaps(
    uploader: ChunkUploader,
) -> tuple[list[SitemapChunk], int, int]:
    languages = settings.SITEMAP_LANGUAGES
    writers = {lang: SitemapChunkWriter(lang) for lang in languages}
    site_url = escape(settings.SITE_URL.rstrip("/"))
    loc_prefixes = {
        lang: f"<url><loc>{site_url}/{lang}".encode("utf-8") for lang in languages
    }

    timings = BuildTimings()
    generated_at = datetime.now(timezone.utc)
    lot_count = 0
    skipped_count = 0
    next_progress_log = PROGRESS_LOG_EVERY
    waiting_since = time.perf_counter()
    async for batch in _stream_lot_batches():
        timings.db_seconds += time.perf_counter() - waiting_since

        for row in batch:
            built = _lot_entry(row, generated_at)
            if built is None:
                skipped_count += 1
                continue
            entry_tail, lastmod = built
            entry_tail_bytes = f"{entry_tail}</url>\n".encode("utf-8")

            for lang, writer in writers.items():
                finished = writer.add(loc_prefixes[lang] + entry_tail_bytes, lastmod)
                if finished is not None:
                    await timings.track_upload_wait(uploader.submit(finished))

        lot_count += len(batch)
        if lot_count >= next_progress_log:
            next_progress_log += PROGRESS_LOG_EVERY
            timings.log_progress(lot_count, len(uploader.uploaded))
        waiting_since = time.perf_counter()

    for writer in writers.values():
        finished = writer.finish()
        if finished is not None:
            await timings.track_upload_wait(uploader.submit(finished))
    await timings.track_upload_wait(uploader.wait())
    timings.log_progress(lot_count, len(uploader.uploaded), final=True)

    chunks = [chunk for writer in writers.values() for chunk in writer.chunks]
    return chunks, lot_count, skipped_count


def _build_index(
    chunks: Iterable[SitemapChunk],
    static_sitemaps: Iterable[tuple[str, datetime | None]],
) -> io.BytesIO:
    entries: list[tuple[str, datetime | None]] = list(static_sitemaps)
    entries.extend((chunk.name, chunk.lastmod) for chunk in chunks)

    parts = [XML_DECLARATION, f'<sitemapindex xmlns="{SITEMAP_NS}">\n']
    for name, lastmod in entries:
        entry = f"<sitemap><loc>{escape(_sitemap_public_url(name))}</loc>"
        if lastmod is not None:
            entry += f"<lastmod>{_w3c_datetime(lastmod)}</lastmod>"
        parts.append(f"{entry}</sitemap>\n")
    parts.append("</sitemapindex>\n")

    return io.BytesIO("".join(parts).encode("utf-8"))


def _list_static_sitemaps(s3: Any) -> list[tuple[str, datetime | None]]:
    paginator = s3.get_paginator("list_objects_v2")
    static_sitemaps = [
        (obj["Key"].removeprefix(settings.SITEMAP_PREFIX), obj.get("LastModified"))
        for page in paginator.paginate(
            Bucket=settings.SITEMAP_BUCKET, Prefix=_sitemap_key(STATIC_SITEMAP_FOLDER)
        )
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(STATIC_SITEMAP_SUFFIXES)
    ]
    if not static_sitemaps:
        logger.warning(
            "No static sitemaps found under {}", _sitemap_key(STATIC_SITEMAP_FOLDER)
        )
    return sorted(static_sitemaps)


def _delete_stale_sitemaps(s3: Any, keep_names: set[str]) -> int:
    static_prefix = _sitemap_key(STATIC_SITEMAP_FOLDER)
    keep_keys = {_sitemap_key(name) for name in keep_names}
    paginator = s3.get_paginator("list_objects_v2")
    keys = [
        obj["Key"]
        for page in paginator.paginate(
            Bucket=settings.SITEMAP_BUCKET, Prefix=settings.SITEMAP_PREFIX
        )
        for obj in page.get("Contents", [])
        if not obj["Key"].startswith(static_prefix) and obj["Key"] not in keep_keys
    ]

    for start in range(0, len(keys), S3_DELETE_BATCH):
        batch = keys[start : start + S3_DELETE_BATCH]
        response = s3.delete_objects(
            Bucket=settings.SITEMAP_BUCKET,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        errors = response.get("Errors")
        if errors:
            raise RuntimeError(
                f"Failed to delete {len(errors)} sitemap objects: {errors[:5]}"
            )
    return len(keys)


async def _async_lambda_handler() -> dict:
    logger.info("Starting sitemap generation")
    s3 = boto3.client("s3")
    uploader = ChunkUploader(s3)

    try:
        chunks, lot_count, skipped_count = await _build_and_upload_lot_sitemaps(
            uploader
        )
    except BaseException:
        await uploader.abort()
        raise

    url_count = sum(chunk.url_count for chunk in chunks)
    logger.info(
        "Uploaded {} lot sitemaps with {} URLs for {} lots ({} skipped, {:.1f} MB)",
        len(chunks),
        url_count,
        lot_count,
        skipped_count,
        _mb(sum(chunk.size for chunk in chunks)),
    )

    static_sitemaps = await asyncio.to_thread(_list_static_sitemaps, s3)
    logger.info("Found {} static sitemaps", len(static_sitemaps))
    index = _build_index(chunks, static_sitemaps)
    await asyncio.to_thread(_upload_fileobj, s3, INDEX_NAME, index)
    logger.info("Uploaded {}", INDEX_NAME)

    keep_names = {chunk.name for chunk in chunks} | {INDEX_NAME}
    deleted_count = await asyncio.to_thread(_delete_stale_sitemaps, s3, keep_names)
    logger.info("Deleted {} stale sitemap objects", deleted_count)

    return {
        "lots": lot_count,
        "urls": url_count,
        "sitemaps": len(chunks),
        "deleted": deleted_count,
    }


def lambda_handler(event, context):
    started_at = time.perf_counter()

    async def run() -> dict:
        try:
            return await _async_lambda_handler()
        finally:
            await engine_async.dispose()

    try:
        return asyncio.run(run())
    except Exception:
        logger.exception("Sitemap generation failed")
        raise
    finally:
        logger.info(
            "Sitemap generation process finished in {:.3f} seconds",
            time.perf_counter() - started_at,
        )


if __name__ == "__main__":
    result = lambda_handler(None, None)
    print(result)
