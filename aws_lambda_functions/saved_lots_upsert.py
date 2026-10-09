import asyncio
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from asyncpg.exceptions import DeadlockDetectedError, LockNotAvailableError
from loguru import logger
from pydantic import HttpUrl
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, and_, false, null, or_, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from auction_api.types.db_lot import DBUpdateLot
from database.db.session import AsyncSessionLocal, engine_async
from database.models.saved_lots import SavedLots


MAX_CONCURRENT_SAVES = 3
SQLITE_MAX_BIND_PARAMETERS = 900
SAVE_STATEMENT_TIMEOUT_MS = 120_000
SAVE_LOCK_TIMEOUT_MS = 30_000
SAVE_IDLE_IN_TRANSACTION_TIMEOUT_MS = 60_000
SAVE_COMMAND_TIMEOUT_SECONDS = 150
SAVE_ATTEMPTS = 3
SAVE_RETRY_DELAY_SECONDS = 5
STALE_SAVE_SESSION_SECONDS = 120
JSON_COLUMNS = frozenset({"copart_exterior_360", "link_img_hd", "link_img_small"})
STRING_COLUMNS = frozenset({"lot_id", "branch_number", "odometer_index", "zip"})
INTEGER_COLUMNS = frozenset({
    "site",
    "salvage_id",
    "odometer",
    "price_new",
    "price_future",
    "current_bid",
    "cost_priced",
    "cost_repair",
    "year",
    "cylinders",
    "location_id",
    "sort_order",
})
FLOAT_COLUMNS = frozenset({"engine_size", "latitude", "longitude"})
BOOL_COLUMNS = frozenset({"is_buynow", "is_offsite", "is_tbo", "is_title_pending"})
DATETIME_COLUMNS = frozenset({"auction_date", "timed_auction_close_date", "updated_at"})
EXCLUDED_COLUMNS = frozenset({"id", "created_at", "is_deleted", "deleted_at"})
UPSERT_COLUMNS = tuple(
    column.name
    for column in SavedLots.__table__.columns
    if column.name not in EXCLUDED_COLUMNS
)
_UPDATED_AT_INDEX = UPSERT_COLUMNS.index("updated_at")
_STAGE_TABLE = "saved_lots_stage"


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _select_expr(name: str, column) -> str:
    quoted = _quote_identifier(name)
    if name == "updated_at":
        return f"COALESCE({quoted}::timestamptz, NOW())"
    if name in JSON_COLUMNS or isinstance(column.type, JSON):
        return f"{quoted}::json"
    if name in DATETIME_COLUMNS or isinstance(column.type, DateTime):
        return f"{quoted}::timestamptz"
    if name in BOOL_COLUMNS or isinstance(column.type, Boolean):
        return f"{quoted}::boolean"
    if name in INTEGER_COLUMNS or isinstance(column.type, Integer):
        return f"{quoted}::integer"
    if name in FLOAT_COLUMNS or isinstance(column.type, Float):
        return f"{quoted}::double precision"
    if "double" in type(column.type).__name__.lower():
        return f"{quoted}::double precision"
    return quoted


def _merge_sql(replace: bool) -> str:
    columns_by_name = {column.name: column for column in SavedLots.__table__.columns}
    insert_columns = [*UPSERT_COLUMNS, "is_deleted"]
    select_exprs = [_select_expr(name, columns_by_name[name]) for name in UPSERT_COLUMNS]
    select_exprs.append("FALSE")
    assignments = [
        f"{_quote_identifier(name)} = EXCLUDED.{_quote_identifier(name)}"
        for name in UPSERT_COLUMNS
        if name not in {"lot_id", "site"}
    ]
    table = _quote_identifier(SavedLots.__tablename__)
    if replace:
        assignments.append(f"{_quote_identifier('is_deleted')} = FALSE")
        assignments.append(f"{_quote_identifier('deleted_at')} = NULL")
        conflict_filter = ""
    else:
        conflict_filter = f"""
WHERE {table}.is_deleted IS FALSE
  AND (
    EXCLUDED.updated_at IS NULL
    OR {table}.updated_at IS NULL
    OR EXCLUDED.updated_at > {table}.updated_at
  )
"""
    return f"""
INSERT INTO {table} (
    {", ".join(_quote_identifier(name) for name in insert_columns)}
)
SELECT {", ".join(select_exprs)}
FROM {_STAGE_TABLE}
ON CONFLICT (lot_id, site) DO UPDATE SET
    {", ".join(assignments)}
{conflict_filter}
"""


_DROP_STAGE_SQL = f"DROP TABLE IF EXISTS {_STAGE_TABLE}"
_CREATE_STAGE_SQL = f"""
CREATE TEMP TABLE {_STAGE_TABLE} (
    {", ".join(f"{_quote_identifier(name)} text" for name in UPSERT_COLUMNS)}
) ON COMMIT DROP
"""
_MERGE_SQL = _merge_sql(replace=False)
_MERGE_REPLACE_SQL = _merge_sql(replace=True)


def _command_count(status: str) -> int:
    parts = str(status).split()
    if not parts:
        return 0
    try:
        return max(int(parts[-1]), 0)
    except ValueError:
        return 0


def create_save_engine(pool_size: int = MAX_CONCURRENT_SAVES) -> AsyncEngine:
    engine_options: dict[str, Any] = {"echo": False}
    if engine_async.dialect.name == "postgresql":
        engine_options["pool_size"] = pool_size
        engine_options["max_overflow"] = 0
        engine_options["pool_timeout"] = 30
        engine_options["connect_args"] = {
            "command_timeout": SAVE_COMMAND_TIMEOUT_SECONDS,
            "server_settings": {
                "statement_timeout": str(SAVE_STATEMENT_TIMEOUT_MS),
                "lock_timeout": str(SAVE_LOCK_TIMEOUT_MS),
                # A killed Lambda leaves its transaction open, holding row locks on saved_lots.
                "idle_in_transaction_session_timeout": str(SAVE_IDLE_IN_TRANSACTION_TIMEOUT_MS),
            },
        }
    return create_async_engine(engine_async.url, **engine_options)


def _coerce_column(column: str, value: Any) -> Any:
    if isinstance(value, HttpUrl):
        value = str(value)
    elif isinstance(value, list):
        value = [str(item) if isinstance(item, HttpUrl) else item for item in value]
    if column in STRING_COLUMNS and value is not None:
        value = str(value)
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _prepare_lot_values(lot: DBUpdateLot) -> dict[str, Any]:
    if lot.lot_id is None or lot.site is None:
        raise ValueError("Updated lot is missing lot_id or site")

    raw = lot.model_dump(exclude={"id", "created_at"}, mode="python")
    return {column: _coerce_column(column, raw.get(column)) for column in UPSERT_COLUMNS}


def _prefer_incoming(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    current_updated = current.get("updated_at")
    incoming_updated = incoming.get("updated_at")
    if incoming_updated is None:
        return current_updated is None
    if current_updated is None:
        return True
    return incoming_updated >= current_updated


def _lot_rows(
    lots: Iterable[DBUpdateLot],
    deleted_keys: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for lot in lots:
        values = _prepare_lot_values(lot)
        key = (values["lot_id"], values["site"])
        if key in deleted_keys:
            continue
        current = rows_by_key.get(key)
        if current is None or _prefer_incoming(current, values):
            rows_by_key[key] = values

    written_at = datetime.now(timezone.utc)
    rows = []
    for key in sorted(rows_by_key):
        values = rows_by_key[key]
        if values.get("updated_at") is None:
            values["updated_at"] = written_at
        rows.append(values)
    return rows


def _prefer_updated(current: str | None, incoming: str | None) -> bool:
    if incoming is None:
        return current is None
    if current is None:
        return True
    return incoming >= current


def _copy_value(column: str, value: Any) -> str | None:
    if value is None:
        return None
    if column in JSON_COLUMNS:
        if isinstance(value, str):
            return value
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def records_from_api_items(items: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    chosen: dict[tuple[str, int], tuple[str | None, tuple[Any, ...]]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("All-lot item must be an object with lot_id and site")
        lot_id = item.get("lot_id")
        site = item.get("site")
        if lot_id is None or site is None:
            raise ValueError("Updated lot is missing lot_id or site")
        key = (str(lot_id), int(site))
        incoming_updated = _copy_value("updated_at", item.get("updated_at"))
        current = chosen.get(key)
        if current is not None and not _prefer_updated(current[0], incoming_updated):
            continue
        record = tuple(_copy_value(column, item.get(column)) for column in UPSERT_COLUMNS)
        chosen[key] = (incoming_updated, record)

    items.clear()
    written_at: str | None = None
    records: list[tuple[Any, ...]] = []
    for key in sorted(chosen):
        updated_at, record = chosen.pop(key)
        if updated_at is None:
            if written_at is None:
                written_at = datetime.now(timezone.utc).isoformat()
            record = (
                *record[:_UPDATED_AT_INDEX],
                written_at,
                *record[_UPDATED_AT_INDEX + 1:],
            )
        records.append(record)
    return records


def _postgres_record(values: dict[str, Any]) -> tuple[Any, ...]:
    record = []
    for column in UPSERT_COLUMNS:
        value = values.get(column)
        if value is None:
            record.append(None)
            continue
        if column in JSON_COLUMNS:
            record.append(json.dumps(value, separators=(",", ":")))
        elif isinstance(value, datetime):
            record.append(value.isoformat())
        elif isinstance(value, bool):
            record.append("true" if value else "false")
        else:
            record.append(value if isinstance(value, str) else str(value))
    return tuple(record)


async def _asyncpg_connection(conn):
    raw = await conn.get_raw_connection()
    driver = raw.driver_connection
    if not hasattr(driver, "copy_records_to_table"):
        raise RuntimeError("PostgreSQL connection does not support COPY")
    return driver


async def _copy_merge(
    engine: AsyncEngine,
    records: list[tuple[Any, ...]],
    replace: bool,
) -> int:
    merge_sql = _MERGE_REPLACE_SQL if replace else _MERGE_SQL
    async with engine.begin() as conn:
        await conn.execute(text(_DROP_STAGE_SQL))
        await conn.execute(text(_CREATE_STAGE_SQL))
        driver = await _asyncpg_connection(conn)
        await driver.copy_records_to_table(
            _STAGE_TABLE,
            records=records,
            columns=list(UPSERT_COLUMNS),
        )
        status = await driver.execute(merge_sql)
        return _command_count(status)


_SAVED_LOTS_WRITERS_SQL = text(f"""
WITH writers AS (
    SELECT DISTINCT
        a.pid,
        a.usename,
        a.application_name,
        a.client_addr::text AS client_addr,
        a.state,
        a.wait_event_type,
        now() - a.xact_start AS xact_age,
        left(a.query, 200) AS query,
        a.usename = current_user
            AND a.xact_start < now() - make_interval(secs => :older_than) AS stale
    FROM pg_stat_activity a
    JOIN pg_locks l ON l.pid = a.pid
    WHERE a.datname = current_database()
      AND a.pid <> pg_backend_pid()
      AND l.granted
      AND l.relation = '{SavedLots.__tablename__}'::regclass
      AND l.mode IN (
          'RowExclusiveLock',
          'ShareRowExclusiveLock',
          'ExclusiveLock',
          'AccessExclusiveLock'
      )
      AND a.xact_start < now() - make_interval(secs => :min_age)
)
SELECT *, CASE WHEN stale THEN pg_terminate_backend(pid) ELSE FALSE END AS terminated
FROM writers
ORDER BY xact_age DESC
""")


async def terminate_stale_save_sessions(
    engine: AsyncEngine,
    older_than_seconds: int = STALE_SAVE_SESSION_SECONDS,
) -> int:
    if engine.dialect.name != "postgresql":
        return 0
    async with engine.begin() as conn:
        result = await conn.execute(
            _SAVED_LOTS_WRITERS_SQL,
            {"older_than": older_than_seconds, "min_age": 10},
        )
        rows = result.all()
    for row in rows:
        logger.warning(
            "Session writing saved_lots: pid={} user={} app={!r} client={} state={} "
            "wait={} transaction_age={} terminated={} query={!r}",
            row.pid,
            row.usename,
            row.application_name,
            row.client_addr,
            row.state,
            row.wait_event_type,
            row.xact_age,
            row.terminated,
            row.query,
        )
    return sum(1 for row in rows if row.terminated)


async def _save_lots_postgres(
    engine: AsyncEngine,
    rows: list[dict[str, Any]],
    replace: bool,
) -> int:
    records = [_postgres_record(row) for row in rows]
    return await _copy_merge(engine, records, replace)


async def save_lot_records(
    records: list[tuple[Any, ...]],
    engine: AsyncEngine | None = None,
    *,
    replace: bool = True,
) -> int:
    if not records:
        return 0

    db_engine = engine or engine_async
    if db_engine.dialect.name != "postgresql":
        raise RuntimeError("COPY lot save requires PostgreSQL")
    attempt = 0
    while True:
        attempt += 1
        try:
            saved = await _copy_merge(db_engine, records, replace)
        except (LockNotAvailableError, DeadlockDetectedError) as exc:
            if attempt == SAVE_ATTEMPTS:
                raise
            logger.warning(
                "Lot save attempt {}/{} hit {}; retrying",
                attempt,
                SAVE_ATTEMPTS,
                type(exc).__name__,
            )
            try:
                await terminate_stale_save_sessions(db_engine)
            except Exception:
                logger.exception("Could not inspect sessions locking saved_lots")
            await asyncio.sleep(SAVE_RETRY_DELAY_SECONDS * attempt)
            continue
        records.clear()
        return saved


async def _save_lots_sqlite(rows: list[dict[str, Any]], replace: bool) -> int:
    columns = (*UPSERT_COLUMNS, "is_deleted")
    batch_size = max(1, SQLITE_MAX_BIND_PARAMETERS // len(columns))
    saved_count = 0
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for offset in range(0, len(rows), batch_size):
                batch = []
                for row in rows[offset:offset + batch_size]:
                    item = {column: row.get(column) for column in UPSERT_COLUMNS}
                    item["is_deleted"] = False
                    batch.append(item)
                statement = sqlite_insert(SavedLots).values(batch)
                update_values = {
                    column: statement.excluded[column]
                    for column in UPSERT_COLUMNS
                    if column not in {"lot_id", "site"}
                }
                if replace:
                    update_values["is_deleted"] = false()
                    update_values["deleted_at"] = null()
                    statement = statement.on_conflict_do_update(
                        index_elements=[SavedLots.lot_id, SavedLots.site],
                        set_=update_values,
                    )
                else:
                    statement = statement.on_conflict_do_update(
                        index_elements=[SavedLots.lot_id, SavedLots.site],
                        set_=update_values,
                        where=and_(
                            SavedLots.is_deleted.is_(False),
                            or_(
                                statement.excluded.updated_at.is_(None),
                                SavedLots.updated_at.is_(None),
                                statement.excluded.updated_at > SavedLots.updated_at,
                            ),
                        ),
                    )
                result = await session.execute(statement)
                if result.rowcount is not None and result.rowcount > 0:
                    saved_count += result.rowcount
    return saved_count


async def save_lots(
    lots: Iterable[DBUpdateLot],
    deleted_keys: set[tuple[str, int]] | None = None,
    engine: AsyncEngine | None = None,
    *,
    replace: bool = False,
) -> int:
    rows = _lot_rows(lots, deleted_keys or set())
    if not rows:
        return 0

    db_engine = engine or engine_async
    dialect_name = db_engine.dialect.name
    if dialect_name == "postgresql":
        return await _save_lots_postgres(db_engine, rows, replace)
    if dialect_name == "sqlite":
        return await _save_lots_sqlite(rows, replace)
    raise RuntimeError(f"Unsupported database dialect for lot upsert: {dialect_name}")
