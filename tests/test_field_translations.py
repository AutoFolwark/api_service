from starlette.requests import Request

from auction_api.types.lot import BasicHistoryLot
from auction_api.types.search import BasicManyHistoryLot
from database.schemas.filters import FilterRead
from schemas.filters import AllFiltersOut
from services.field_translations import (
    get_locale,
    translate_filters,
    translate_lot_response,
)


def _request(cookie: str | None = None) -> Request:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"NEXT_LOCALE={cookie}".encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": headers,
        }
    )


def test_missing_and_unknown_cookie_use_english():
    assert get_locale(_request()) == "en"
    assert get_locale(_request("")) == "en"
    assert get_locale(_request("fr")) == "en"
    assert get_locale(_request(" PL ")) == "pl"


def test_polish_translates_known_fields_and_leaves_unknown_values():
    lot = BasicHistoryLot(
        fuel="Gasoline",
        odobrand="not_actual",
        color="not-a-color",
        status="Starts",
        sale_status="Sold",
    )

    translated = translate_lot_response(lot, "pl")

    assert translated.fuel == "Benzyna"
    assert translated.odobrand == "Niezgodny z rzeczywistym"
    assert translated.color == "not-a-color"
    assert translated.status == "Odpala"
    assert translated.sale_status == "Sold"
    assert lot.fuel == "Gasoline"


def test_english_locale_uses_english_labels():
    lot = BasicHistoryLot(odobrand="not_actual", fuel="Gasoline")
    translated = translate_lot_response(lot, "en")

    assert translated.odobrand == "Not actual"
    assert translated.fuel == "Gasoline"


def test_list_response_translates_each_lot():
    page = BasicManyHistoryLot(
        size=1,
        page=1,
        pages=1,
        count=1,
        data=[BasicHistoryLot(fuel="Diesel", sale_status="Sold")],
    )

    translated = translate_lot_response(page, "cs")

    assert translated.data[0].fuel == "Nafta"
    assert translated.data[0].sale_status == "Sold"
    assert page.data[0].fuel == "Diesel"


def test_filter_names_translate_and_slugs_stay():
    filters = AllFiltersOut(
        damage=[],
        document=[],
        vehicle_type=[],
        drive=[FilterRead(id=1, name="All Wheel Drive", slug="all-wheel-drive")],
        transmission=[FilterRead(id=2, name="Automatic", slug="automatic")],
        status=[FilterRead(id=3, name="Run & Drive", slug="run-drive")],
    )

    translated = translate_filters(filters, "de")

    assert translated.drive[0].name == "Allradantrieb"
    assert translated.drive[0].slug == "all-wheel-drive"
    assert translated.transmission[0].name == "Automatik"
    assert translated.status[0].name == "Startet und fährt"
    assert filters.drive[0].name == "All Wheel Drive"
