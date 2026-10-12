import re
from datetime import UTC, datetime

from rfc9457 import NotFoundProblem
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from auction_api.types.search import CommonSearchParams, DecodedSearch
from database.models.car_make import Make
from database.models.car_model import Model

# Split on whitespace, commas, hyphens, and underscores.
# "1-series" and "1 series" then produce the same tokens.
_TOKEN_SPLIT = re.compile(r"[\s,\-_]+")
_MAX_NGRAM = 4
_AUTOMOBILE = "automobile"
_YEAR_MIN = 1900


def _tokens(query: str) -> list[str]:
    return [part for part in _TOKEN_SPLIT.split(query.strip().lower()) if part]


def _ngram_spans(tokens: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Map each slug to the token ranges that produce it.

    "bmw 1 series" yields slugs bmw, 1, series, bmw-1, 1-series, and bmw-1-series.
    A span is (start, end) indexes into tokens. The same slug can appear twice.
    """
    spans: dict[str, list[tuple[int, int]]] = {}
    count = len(tokens)
    max_n = min(_MAX_NGRAM, count)
    for length in range(1, max_n + 1):
        for start in range(count - length + 1):
            slug = slugify(" ".join(tokens[start : start + length]))
            if not slug:
                continue
            spans.setdefault(slug, []).append((start, start + length))
    return spans


def _parse_year(token: str, today_year: int) -> int | None:
    """Accept a 4-digit year, or a 2-digit year like 10 -> 2010 and 99 -> 1999.

    A 2-digit year maps to the 2000s when it is not past next year, otherwise the 1900s.
    """
    if not token.isdigit():
        return None
    if len(token) == 4:
        year = int(token)
        if _YEAR_MIN <= year <= today_year + 1:
            return year
        return None
    if len(token) == 2:
        year_short = int(token)
        if year_short <= (today_year % 100) + 1:
            return 2000 + year_short
        return 1900 + year_short
    return None


def _vehicle_type_rank(
    slug: str | None, name: str | None, requested: str | None
) -> tuple[int, int]:
    """Higher is better. Prefer the requested type, otherwise automobile.

    The same slug exists once per vehicle type (BMW is both a car and a motorcycle).
    """
    slug_norm = (slug or "").casefold()
    name_norm = (name or "").casefold()
    if requested:
        requested_norm = requested.casefold()
        preferred = int(slug_norm == requested_norm or name_norm == requested_norm)
    else:
        preferred = int(slug_norm == _AUTOMOBILE)
    return preferred, int(slug_norm == _AUTOMOBILE)


def _best_span(
    spans_by_slug: dict[str, list[tuple[int, int]]],
    slug: str,
    consumed: set[int],
) -> tuple[int, int] | None:
    """Longest unused token range for this slug. Equal lengths keep the leftmost."""
    best: tuple[int, int] | None = None
    for start, end in spans_by_slug.get(slug, []):
        if any(index in consumed for index in range(start, end)):
            continue
        length = end - start
        if (
            best is None
            or length > best[1] - best[0]
            or (length == best[1] - best[0] and start < best[0])
        ):
            best = (start, end)
    return best


def _pick_make(
    makes: list[Make],
    spans_by_slug: dict[str, list[tuple[int, int]]],
    consumed: set[int],
    requested_vehicle_type: str | None,
) -> tuple[Make, int, int] | None:
    """Longest make slug wins, so "land rover" beats "rover".

    Returns the make and the token range it used.
    """
    best: tuple[tuple[int, int, int, int, int], Make, int, int] | None = None
    for make in makes:
        span = _best_span(spans_by_slug, make.slug, consumed)
        if span is None:
            continue
        start, end = span
        vehicle_type = make.vehicle_type
        preferred, automobile = _vehicle_type_rank(
            vehicle_type.slug if vehicle_type is not None else None,
            vehicle_type.name if vehicle_type is not None else None,
            requested_vehicle_type,
        )
        key = (-(end - start), -preferred, -automobile, start, make.id)
        if best is None or key < best[0]:
            best = (key, make, start, end)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _pick_model(
    models: list[Model],
    spans_by_slug: dict[str, list[tuple[int, int]]],
    consumed: set[int],
    requested_vehicle_type: str | None,
) -> tuple[Model, int, int] | None:
    """Longest exact model slug wins, so "prius" matches Prius and not Prius C."""
    best: tuple[tuple[int, int, int, int, int], Model, int, int] | None = None
    for model in models:
        span = _best_span(spans_by_slug, model.slug, consumed)
        if span is None:
            continue
        start, end = span
        vehicle_type = model.make.vehicle_type if model.make is not None else None
        preferred, automobile = _vehicle_type_rank(
            vehicle_type.slug if vehicle_type is not None else None,
            vehicle_type.name if vehicle_type is not None else None,
            requested_vehicle_type,
        )
        key = (-(end - start), -preferred, -automobile, start, model.id)
        if best is None or key < best[0]:
            best = (key, model, start, end)
    if best is None:
        return None
    return best[1], best[2], best[3]


async def decode_search_query(
    query: str,
    db: AsyncSession,
    vehicle_type: str | None = None,
) -> DecodedSearch:
    """Turn free text into a year, make, and model using the make and model tables.

    Make is matched first, then model on the remaining tokens. A model with no make
    in the text, such as "2016 camry", supplies the make from the model row.
    Tokens used by the make or model are skipped when reading the year, so a model
    number like Alfa Romeo 159 is not treated as a year.
    """
    tokens = _tokens(query)
    spans_by_slug = _ngram_spans(tokens)
    slugs = list(spans_by_slug)
    consumed: set[int] = set()

    chosen_make: Make | None = None
    if slugs:
        make_rows = (
            (
                await db.execute(
                    select(Make)
                    .where(Make.slug.in_(slugs))
                    .options(joinedload(Make.vehicle_type))
                )
            )
            .unique()
            .scalars()
            .all()
        )
        picked_make = _pick_make(list(make_rows), spans_by_slug, consumed, vehicle_type)
        if picked_make is not None:
            chosen_make, start, end = picked_make
            consumed.update(range(start, end))

    chosen_model: Model | None = None
    if slugs:
        model_stmt = (
            select(Model)
            .join(Make)
            .where(Model.slug.in_(slugs))
            .options(joinedload(Model.make).joinedload(Make.vehicle_type))
        )
        if chosen_make is not None:
            model_stmt = model_stmt.where(Model.make_id == chosen_make.id)
        model_rows = (await db.execute(model_stmt)).unique().scalars().all()
        picked_model = _pick_model(
            list(model_rows), spans_by_slug, consumed, vehicle_type
        )
        if picked_model is not None:
            chosen_model, start, end = picked_model
            consumed.update(range(start, end))
            # "2016 camry" names no make; take it from the matched model.
            if chosen_make is None:
                chosen_make = chosen_model.make

    today_year = datetime.now(UTC).year
    year: int | None = None
    year_index: int | None = None
    for index, token in enumerate(tokens):
        if index in consumed:
            continue
        parsed = _parse_year(token, today_year)
        if parsed is None:
            continue
        year = parsed
        year_index = index
        break

    unrecognized = [
        token
        for index, token in enumerate(tokens)
        if index not in consumed and index != year_index
    ]
    return DecodedSearch(
        query=query,
        year=year,
        make=chosen_make.name if chosen_make is not None else None,
        make_slug=chosen_make.slug if chosen_make is not None else None,
        model=chosen_model.name if chosen_model is not None else None,
        model_slug=chosen_model.slug if chosen_model is not None else None,
        unrecognized=unrecognized,
    )


def require_decoded_search(decoded: DecodedSearch) -> None:
    """404 when the text matched no year, make, or model. Partial matches still pass."""
    if decoded.year is None and decoded.make is None and decoded.model is None:
        raise NotFoundProblem("Could not decode year, make or model from search query")


def apply_decoded_search(params: CommonSearchParams, decoded: DecodedSearch) -> None:
    """Fill empty make, model, and year filters. Explicit query params are left as sent.

    Make and model are set to slugs; transform_slugs turns those into names afterward.
    """
    if not params.make and decoded.make_slug:
        params.make = decoded.make_slug
    if not params.model and decoded.model_slug:
        params.model = decoded.model_slug
    if decoded.year is not None and params.year_from is None and params.year_to is None:
        params.year_from = decoded.year
        params.year_to = decoded.year
