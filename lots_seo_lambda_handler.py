import asyncio
from collections.abc import Iterable
from itertools import islice
import time
from typing import Any

from loguru import logger
from pydantic import HttpUrl
from sqlalchemy import func, tuple_, update
from datetime import datetime, timedelta, timezone
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from auction_api.api import AuctionApiClient
from auction_api.types.db_lot import DBDeleteLot, DBUpdateLot
from database.db.session import AsyncSessionLocal, engine_async
from database.models.saved_lots import SavedLots
from request_schemas.db_save_schemas import DBCurrentDeleteIn, DBCurrentUpdateIn


PAGE_SIZE = 1000
MAX_CONCURRENT_PAGE_REQUESTS = 8
POSTGRES_MAX_BIND_PARAMETERS = 32767
SQLITE_MAX_BIND_PARAMETERS = 900


def _get_date_range() -> tuple[str, str]:
    date_from = (datetime.now(tz=timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    date_to = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return date_from, date_to


async def _fetch_deleted_lots(
    api: AuctionApiClient, date_from: str, date_to: str
) -> list[DBDeleteLot]:
    request = DBCurrentDeleteIn(date_from=date_from, date_to=date_to)
    response = await api.request_with_schema(api.GET_DB_DELETED_LOTS, request)
    return response.data


async def _mark_deleted_lots(
    lots: Iterable[DBDeleteLot],
) -> tuple[set[tuple[str, int]], int]:
    deleted_keys = {
        (str(lot.lot_id), lot.site)
        for lot in lots
    }
    if not deleted_keys:
        return deleted_keys, 0

    deleted_at = datetime.now(timezone.utc)
    marked_count = 0
    deleted_key_iterator = iter(deleted_keys)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            while batch := list(islice(deleted_key_iterator, SQLITE_MAX_BIND_PARAMETERS // 2)):
                result = await session.execute(
                    update(SavedLots)
                    .where(
                        tuple_(SavedLots.lot_id, SavedLots.site).in_(batch),
                        SavedLots.is_deleted.is_(False),
                    )
                    .values(is_deleted=True, deleted_at=deleted_at)
                )
                marked_count += result.rowcount or 0
    return deleted_keys, marked_count


async def _fetch_all_updated_lots(
    api: AuctionApiClient,
    date_from: str,
    date_to: str,
    deleted_keys: set[tuple[str, int]],
) -> tuple[int, int]:

    logger.info(f"Fetching updated lots from {date_from} to {date_to}")

    request = DBCurrentUpdateIn.model_validate(
        {
            "date_from": date_from,
            "date_to": date_to,
            "page": 1,
            "size": PAGE_SIZE,
        }
    )
    first_page = await api.request_with_schema(api.GET_DB_UPDATED_LOTS, request)
    total_pages = first_page.pages
    fetched_count = len(first_page.data)
    saved_count = await _save_lots(first_page.data, deleted_keys)
    del first_page
    pages_processed = 1

    async def fetch_page(page: int) -> list[DBUpdateLot]:
        page_request = request.model_copy(update={"page": page})
        response = await api.request_with_schema(api.GET_DB_UPDATED_LOTS, page_request)
        return response.data

    for page_start in range(2, total_pages + 1, MAX_CONCURRENT_PAGE_REQUESTS):
        page_end = min(page_start + MAX_CONCURRENT_PAGE_REQUESTS, total_pages + 1)
        page_results = await asyncio.gather(
            *(fetch_page(page) for page in range(page_start, page_end))
        )
        for page_lots in page_results:
            fetched_count += len(page_lots)
            saved_count += await _save_lots(page_lots, deleted_keys)
            pages_processed += 1
            del page_lots
        del page_results

    return fetched_count, saved_count


def _lot_values(lot: DBUpdateLot) -> dict[str, Any]:
    values = lot.model_dump(
        exclude={"id", "created_at", "updated_at"},
        exclude_unset=True,
        mode="python",
    )
    if lot.lot_id is None or lot.site is None:
        raise ValueError("Updated lot is missing lot_id or site")

    values["lot_id"] = str(lot.lot_id)
    for key in ("branch_number", "odometer_index", "zip"):
        if values.get(key) is not None:
            values[key] = str(values[key])

    for key, value in values.items():
        if isinstance(value, HttpUrl):
            values[key] = str(value)
        elif isinstance(value, list):
            values[key] = [str(item) if isinstance(item, HttpUrl) else item for item in value]
    return values


def _unique_lot_values(lots: Iterable[DBUpdateLot]) -> list[dict[str, Any]]:
    values_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for lot in lots:
        values = _lot_values(lot)
        values_by_key[(values["lot_id"], values["site"])] = values
    return list(values_by_key.values())


async def _save_lots(
    lots: Iterable[DBUpdateLot],
    deleted_keys: set[tuple[str, int]] | None = None,
) -> int:
    deleted_keys = deleted_keys or set()
    values = [
        value
        for value in _unique_lot_values(lots)
        if (value["lot_id"], value["site"]) not in deleted_keys
    ]
    if not values:
        return 0

    dialect_name = engine_async.dialect.name
    if dialect_name not in {"postgresql", "sqlite"}:
        raise RuntimeError(f"Unsupported database dialect for lot upsert: {dialect_name}")
    insert = postgresql_insert if dialect_name == "postgresql" else sqlite_insert

    saved_count = 0
    async with AsyncSessionLocal() as session:
        async with session.begin():
            groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
            for value in values:
                columns = tuple(sorted(value))
                groups.setdefault(columns, []).append(
                    {column: value[column] for column in columns}
                )

            for columns, group in groups.items():
                if dialect_name == "postgresql":
                    batch_size = max(
                        1, POSTGRES_MAX_BIND_PARAMETERS // len(columns)
                    )
                else:
                    batch_size = max(1, SQLITE_MAX_BIND_PARAMETERS // len(columns))

                for offset in range(0, len(group), batch_size):
                    batch = group[offset:offset + batch_size]
                    statement = insert(SavedLots).values(batch)
                    update_values = {
                        key: statement.excluded[key]
                        for key in columns
                        if key not in {"lot_id", "site"}
                    }
                    update_values["updated_at"] = func.now()
                    statement = statement.on_conflict_do_update(
                        index_elements=[SavedLots.lot_id, SavedLots.site],
                        set_=update_values,
                        where=SavedLots.is_deleted.is_(False),
                    )
                    result = await session.execute(statement)
                    saved_count += result.rowcount or 0
    return saved_count


async def _async_lambda_handler() -> dict:
    date_from, date_to = _get_date_range()
    api = AuctionApiClient()

    deleted_lots = await _fetch_deleted_lots(api, date_from, date_to)
    deleted_keys, marked_count = await _mark_deleted_lots(deleted_lots)
    del deleted_lots

    fetched_count, saved_count = await _fetch_all_updated_lots(
        api, date_from, date_to, deleted_keys
    )
    return {
        "deleted_count": marked_count,
        "deleted_keys_count": len(deleted_keys),
        "fetched_count": fetched_count,
        "saved_count": saved_count,
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
    finally:
        logger.info(
            "Lot sync process finished",
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
        )

if __name__ == "__main__":
    result = lambda_handler(None, None)
    print(result)
