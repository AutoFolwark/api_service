import asyncio

import pytest
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from auction_api.types.search import CurrentSearchParams
from database.models.base import Base
from database.models.car_make import Make
from database.models.car_model import Model
from database.models.vehicle_type import VehicleType
from services.search_query_decoder import (
    apply_decoded_search,
    decode_search_query,
    require_decoded_search,
)


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            VehicleType(id=1, name="Automobile", slug="automobile"),
            VehicleType(id=2, name="Motorcycle", slug="motorcycle"),
            Make(id=4, name="BMW", slug="bmw", vehicle_type_id=1),
            Make(id=62, name="BMW", slug="bmw", vehicle_type_id=2),
            Make(id=41, name="Toyota", slug="toyota", vehicle_type_id=1),
            Model(id=92, name="1 Series", slug="1-series", make_id=4),
            Model(id=828, name="Prius", slug="prius", make_id=41),
            Model(id=816, name="Prius C", slug="prius-c", make_id=41),
            Model(id=809, name="Camry", slug="camry", make_id=41),
        ]
    )
    await session.commit()


def _run(test):
    async def _wrapper():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    VehicleType.__table__,
                    Make.__table__,
                    Model.__table__,
                ],
            )
        try:
            async with session_factory() as session:
                await _seed(session)
                await test(session)
        finally:
            await engine.dispose()

    asyncio.run(_wrapper())


def test_bmw_1_series_with_year():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("bmw 1 series 2010", session)
        assert decoded.year == 2010
        assert decoded.make == "BMW"
        assert decoded.make_slug == "bmw"
        assert decoded.model == "1 Series"
        assert decoded.model_slug == "1-series"
        assert decoded.unrecognized == []

    _run(_case)


def test_toyota_prius_two_digit_year():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("toyota prius 10", session)
        assert decoded.year == 2010
        assert decoded.make == "Toyota"
        assert decoded.make_slug == "toyota"
        assert decoded.model == "Prius"
        assert decoded.model_slug == "prius"
        assert decoded.unrecognized == []

    _run(_case)


def test_two_digit_year_in_previous_century():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("camry 99", session)
        assert decoded.year == 1999
        assert decoded.make == "Toyota"
        assert decoded.model == "Camry"

    _run(_case)


def test_model_infers_make():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("2016 camry", session)
        assert decoded.year == 2016
        assert decoded.make == "Toyota"
        assert decoded.make_slug == "toyota"
        assert decoded.model == "Camry"
        assert decoded.model_slug == "camry"
        assert decoded.unrecognized == []

    _run(_case)


def test_partial_match_lists_unrecognized_words():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("blue bmw 2010", session)
        require_decoded_search(decoded)
        assert decoded.year == 2010
        assert decoded.make == "BMW"
        assert decoded.model is None
        assert decoded.unrecognized == ["blue"]

    _run(_case)


def test_unrecognized_query_raises_not_found():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("asdf qwerty", session)
        assert decoded.year is None
        assert decoded.make is None
        assert decoded.model is None
        with pytest.raises(NotFoundProblem):
            require_decoded_search(decoded)

    _run(_case)


def test_explicit_params_win():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("bmw 1 series 2010", session)
        params = CurrentSearchParams(
            site="1",
            make="audi",
            model="a4",
            year_from=2001,
            year_to=2002,
            search="bmw 1 series 2010",
        )
        apply_decoded_search(params, decoded)
        assert params.make == "audi"
        assert params.model == "a4"
        assert params.year_from == 2001
        assert params.year_to == 2002
        assert "search" not in params.model_dump()

    _run(_case)


def test_decoded_values_fill_missing_params():
    async def _case(session: AsyncSession):
        decoded = await decode_search_query("2016 camry", session)
        params = CurrentSearchParams(site="1")
        apply_decoded_search(params, decoded)
        assert params.make == "toyota"
        assert params.model == "camry"
        assert params.year_from == 2016
        assert params.year_to == 2016

    _run(_case)
