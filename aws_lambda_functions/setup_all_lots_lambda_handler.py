import asyncio
import time
from typing import Any

import httpx
import orjson
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine

from auction_api.api import AuctionApiClient
from aws_lambda_functions.saved_lots_upsert import (
    create_save_engine,
    records_from_api_items,
    save_lot_records,
    terminate_stale_save_sessions,
)
from database.db.session import engine_async


PAGE_SIZE = 5000
WORKERS = 3
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_SECONDS = 90
FETCH_RETRY_DELAY_SECONDS = 2


async def _fetch_all_lot_page(
    client: httpx.AsyncClient,
    api: AuctionApiClient,
    page: int,
) -> tuple[list[dict[str, Any]], int | None]:
    attempt = 0
    while True:
        attempt += 1
        logger.debug("Fetching all-lot page {} (attempt {}/{})", page, attempt, FETCH_ATTEMPTS)
        started_at = time.perf_counter()
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                data, page_count = await _request_all_lot_page(client, api, page)
        except Exception as exc:
            if attempt == FETCH_ATTEMPTS:
                raise RuntimeError(
                    f"All-lot page {page} failed after {FETCH_ATTEMPTS} attempts"
                ) from exc
            logger.warning(
                "All-lot page {} attempt {}/{} failed after {:.1f}s: {!r}; retrying",
                page,
                attempt,
                FETCH_ATTEMPTS,
                time.perf_counter() - started_at,
                exc,
            )
            await asyncio.sleep(FETCH_RETRY_DELAY_SECONDS * attempt)
            continue
        logger.debug(
            "Fetched all-lot page {}: {} lots in {:.1f}s",
            page,
            len(data),
            time.perf_counter() - started_at,
        )
        return data, page_count


async def _request_all_lot_page(
    client: httpx.AsyncClient,
    api: AuctionApiClient,
    page: int,
) -> tuple[list[dict[str, Any]], int | None]:
    url = api._build_url(api.GET_DB_ALL_LOTS.endpoint.value)
    response = await client.get(
        url,
        params={"page": page, "size": PAGE_SIZE},
        headers={api.header_name: api.api_key},
    )

    try:
        content = response.content
        status_code = response.status_code
    finally:
        await response.aclose()

    if status_code != httpx.codes.OK:
        preview = content[:200].decode("utf-8", errors="replace")
        del content
        raise RuntimeError(
            f"All-lot page {page} failed with status {status_code}: {preview}"
        )

    try:
        payload = orjson.loads(content)
    except orjson.JSONDecodeError as exc:
        del content
        raise RuntimeError(f"All-lot page {page} returned invalid JSON") from exc
    del content

    if not isinstance(payload, dict):
        raise RuntimeError(f"All-lot page {page} returned invalid JSON")
    data = payload.get("data")
    pages = payload.get("pages")
    del payload
    if not isinstance(data, list):
        raise RuntimeError(f"All-lot page {page} is missing data")

    page_count = None
    if isinstance(pages, int) and not isinstance(pages, bool) and pages >= 0:
        page_count = pages
    return data, page_count


async def _fetch_all_lots(
    api: AuctionApiClient,
    client: httpx.AsyncClient,
    save_engine: AsyncEngine,
) -> tuple[int, int]:
    logger.info("Fetching all lots")
    try:
        first_items, total_pages = await _fetch_all_lot_page(client, api, 1)
    except Exception:
        logger.exception("Failed to process all-lot page {}", 1)
        raise

    if total_pages is None:
        first_items.clear()
        raise RuntimeError("All-lot feed is missing page count")
    logger.info("All-lot feed has {} pages", total_pages)
    if total_pages < 1:
        first_items.clear()
        return 0, 0

    try:
        first_fetched = len(first_items)
        first_records = records_from_api_items(first_items)
    except Exception:
        logger.exception("Failed to process all-lot page {}", 1)
        raise
    finally:
        first_items.clear()

    progress_lock = asyncio.Lock()
    page_lock = asyncio.Lock()
    in_flight_downloads: set[asyncio.Task] = set()
    next_page = 2
    fetched_count = 0
    saved_count = 0
    completed_pages = 0

    async def take_page() -> int | None:
        nonlocal next_page
        async with page_lock:
            if next_page > total_pages:
                return None
            page = next_page
            next_page += 1
            return page

    async def fetch_records(page: int) -> tuple[list[tuple[Any, ...]], int]:
        items, _page_count = await _fetch_all_lot_page(client, api, page)
        try:
            fetched = len(items)
            return records_from_api_items(items), fetched
        finally:
            items.clear()

    def start_download(page: int) -> asyncio.Task:
        task = asyncio.create_task(
            fetch_records(page),
            name=f"all-lots-page-{page}",
        )
        in_flight_downloads.add(task)
        return task

    def release_download(task: asyncio.Task | None) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
            return
        if not task.cancelled():
            task.exception()
        in_flight_downloads.discard(task)

    async def save_page(page: int, records: list[tuple[Any, ...]]) -> tuple[int, float]:
        logger.debug("Saving all-lot page {} ({} records)", page, len(records))
        started_at = time.perf_counter()
        saved = await save_lot_records(records, save_engine, replace=True)
        return saved, time.perf_counter() - started_at

    async def record_progress(
        page: int,
        page_fetched: int,
        page_saved: int,
        save_seconds: float,
    ) -> None:
        nonlocal fetched_count, saved_count, completed_pages
        async with progress_lock:
            fetched_count += page_fetched
            saved_count += page_saved
            completed_pages += 1
            logger.info(
                "Saved page {} in {:.1f}s; processed {}/{} pages: fetched {}, saved {} lots",
                page,
                save_seconds,
                completed_pages,
                total_pages,
                fetched_count,
                saved_count,
            )

    async def load_page(page: int) -> tuple[list[tuple[Any, ...]], int]:
        try:
            return await fetch_records(page)
        except Exception:
            logger.exception("Failed to process all-lot page {}", page)
            raise

    async def worker(
        initial: tuple[int, list[tuple[Any, ...]], int] | None,
    ) -> None:
        if initial is None:
            page_number = await take_page()
            if page_number is None:
                return
            records, fetched = await load_page(page_number)
            page = page_number
        else:
            page, records, fetched = initial

        download: asyncio.Task | None = None
        while True:
            next_page_number = await take_page()
            if next_page_number is not None:
                download = start_download(next_page_number)
            try:
                saved, save_seconds = await save_page(page, records)
            except asyncio.CancelledError:
                release_download(download)
                raise
            except Exception:
                logger.exception("Failed to process all-lot page {}", page)
                release_download(download)
                raise
            del records
            await record_progress(page, fetched, saved, save_seconds)
            if download is None:
                return
            try:
                records, fetched = await download
            except asyncio.CancelledError:
                release_download(download)
                raise
            except Exception:
                logger.exception("Failed to process all-lot page {}", next_page_number)
                release_download(download)
                raise
            in_flight_downloads.discard(download)
            download = None
            page = next_page_number

    workers = [
        asyncio.create_task(worker((1, first_records, first_fetched))),
        *[asyncio.create_task(worker(None)) for _ in range(WORKERS - 1)],
    ]
    del first_records
    try:
        try:
            await asyncio.gather(*workers)
        except Exception:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
    finally:
        pending = list(in_flight_downloads)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        in_flight_downloads.clear()
    return fetched_count, saved_count


async def _async_lambda_handler() -> dict:
    logger.info("Starting full lot load")
    save_engine = create_save_engine(pool_size=WORKERS)
    try:
        try:
            terminated = await terminate_stale_save_sessions(save_engine)
        except Exception:
            logger.exception("Could not clean up stale lot-save sessions; continuing")
        else:
            logger.info("Terminated {} stale lot-save sessions", terminated)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0, pool=30.0),
            limits=httpx.Limits(
                max_connections=WORKERS,
                max_keepalive_connections=WORKERS,
            ),
        ) as http_client:
            api = AuctionApiClient()
            fetched_count, saved_count = await _fetch_all_lots(api, http_client, save_engine)
            logger.info(
                "Full lot load complete: {} lots fetched, {} saved",
                fetched_count,
                saved_count,
            )
            return {
                "fetched_count": fetched_count,
                "saved_count": saved_count,
            }
    finally:
        await save_engine.dispose()


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
        logger.exception("Full lot load failed")
        raise
    finally:
        logger.info(
            "Full lot load process finished in {:.3f} seconds",
            time.perf_counter() - started_at,
        )


if __name__ == "__main__":
    result = lambda_handler(None, None)
    print(result)
