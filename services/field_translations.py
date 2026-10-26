import json
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from auction_api.types.lot import BasicLot
from auction_api.types.search import BasicManyCurrentLots, BasicManyHistoryLot
from database.schemas.filters import FilterRead
from schemas.filters import AllFiltersOut

COOKIE_NAME = "NEXT_LOCALE"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = frozenset({"en", "pl", "uk", "cs", "de", "sl"})
TRANSLATABLE_FIELDS = (
    "keys",
    "odobrand",
    "fuel",
    "drive",
    "transmission",
    "color",
    "status",
    "body_type",
)
FILTER_NAME_FIELDS = ("drive", "transmission", "status")

_TRANSLATIONS_PATH = (
    Path(__file__).resolve().parent.parent / "translations" / "lot_field_values.json"
)


@lru_cache(maxsize=1)
def _load_translations() -> tuple[
    dict[str, dict[str, dict[str, str]]], dict[str, dict[str, str]]
]:
    raw = json.loads(_TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    folded: dict[str, dict[str, str]] = {}
    for field, values in raw.items():
        folded[field] = {key.casefold(): key for key in values}
    return raw, folded


def get_locale(request: Request) -> str:
    raw = request.cookies.get(COOKIE_NAME, "")
    code = raw.strip().lower()
    if code in SUPPORTED_LOCALES:
        return code
    return DEFAULT_LOCALE


def translate_value(field: str, value: str | None, locale: str) -> str | None:
    if not value:
        return value
    translations, folded = _load_translations()
    field_map = translations.get(field)
    if not field_map:
        return value
    entry = field_map.get(value)
    if entry is None:
        canonical = folded.get(field, {}).get(value.casefold())
        if canonical is not None:
            entry = field_map[canonical]
    if entry is None:
        return value
    return entry.get(locale) or entry.get(DEFAULT_LOCALE) or value


def translate_lot(lot: BasicLot, locale: str) -> BasicLot:
    updates = {}
    for field in TRANSLATABLE_FIELDS:
        raw = getattr(lot, field, None)
        if not isinstance(raw, str) or not raw:
            continue
        translated = translate_value(field, raw, locale)
        if translated != raw:
            updates[field] = translated
    if not updates:
        return lot
    return lot.model_copy(update=updates)


def translate_lot_response(payload, locale: str):
    if payload is None:
        return None
    if isinstance(payload, list):
        return [translate_lot_response(item, locale) for item in payload]
    if isinstance(payload, (BasicManyCurrentLots, BasicManyHistoryLot)):
        return payload.model_copy(
            update={"data": [translate_lot(lot, locale) for lot in payload.data]}
        )
    if isinstance(payload, BasicLot):
        return translate_lot(payload, locale)
    return payload


def _translate_filter_names(
    field: str, items: list[FilterRead], locale: str
) -> list[FilterRead]:
    translated = []
    for item in items:
        name = translate_value(field, item.name, locale)
        if name != item.name:
            item = item.model_copy(update={"name": name})
        translated.append(item)
    return translated


def translate_filters(filters: AllFiltersOut, locale: str) -> AllFiltersOut:
    return filters.model_copy(
        update={
            field: _translate_filter_names(field, getattr(filters, field), locale)
            for field in FILTER_NAME_FIELDS
        }
    )
