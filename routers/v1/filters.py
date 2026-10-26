from fastapi import APIRouter, Depends, Path
from fastapi_cache import default_key_builder
from fastapi_cache.decorator import cache
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.car_make import MakeService
from database.crud.car_model import ModelService
from database.crud.damage import DamageService
from database.crud.document import DocumentService
from database.crud.drive import DriveService
from database.crud.status import StatusService
from database.crud.transmission import TransmissionService
from database.crud.vehicle_type import VehicleTypeService
from database.db.session import get_async_db
from database.schemas.filters import FilterRead
from schemas.filters import AllFiltersOut
from services.field_translations import get_locale, translate_filters

filters_router = APIRouter()


@filters_router.get(
    "/all-filters", description="Get all static filters", response_model=AllFiltersOut
)
@cache(expire=60 * 360, key_builder=default_key_builder)
async def filters(
    db: AsyncSession = Depends(get_async_db),
    locale: str = Depends(get_locale),
):
    damage_service = DamageService(db)
    document_service = DocumentService(db)
    drive_service = DriveService(db)
    status_service = StatusService(db)
    transmission_service = TransmissionService(db)
    vehicle_type_service = VehicleTypeService(db)

    return translate_filters(
        AllFiltersOut(
            damage=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await damage_service.get_all_sorted("name")
            ],
            document=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await document_service.get_all_sorted("name")
            ],
            drive=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await drive_service.get_all_sorted("name")
            ],
            status=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await status_service.get_all_sorted("name")
            ],
            transmission=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await transmission_service.get_all_sorted("name")
            ],
            vehicle_type=[
                FilterRead.model_validate(filter_obj)
                for filter_obj in await vehicle_type_service.get_all_sorted("name")
            ],
        ),
        locale,
    )


@filters_router.get(
    "/{vehicle_type_slug}/makes",
    description="Get all static filters",
    response_model=list[FilterRead],
)
async def filters(
    vehicle_type_slug: str = Path(..., description="Vehicle type slug"),
    db: AsyncSession = Depends(get_async_db),
):
    make_service = MakeService(db)
    vehicle_type_service = VehicleTypeService(db)

    vehicle_type = await vehicle_type_service.get_by_field("slug", vehicle_type_slug)
    if not vehicle_type:
        raise NotFoundProblem(detail="Vehicle type not found")

    makes = await make_service.get_makes_by_vehicle_type(vehicle_type)
    if not makes:
        return []
    return [FilterRead.model_validate(make_obj) for make_obj in makes]


@filters_router.get(
    "/{vehicle_type_slug}/makes/{make_slug}/models",
    description="Get all models by make and vehicle type",
    response_model=list[FilterRead],
)
async def filters(
    vehicle_type_slug: str = Path(..., description="Vehicle type slug"),
    make_slug: str = Path(..., description="Make slug"),
    db: AsyncSession = Depends(get_async_db),
) -> list[FilterRead]:
    make_service = MakeService(db)
    vehicle_type_service = VehicleTypeService(db)
    model_service = ModelService(db)

    vehicle_type = await vehicle_type_service.get_by_field("slug", vehicle_type_slug)
    if not vehicle_type:
        raise NotFoundProblem(detail="Vehicle type not found")

    make = await make_service.get_make_by_slug_vehicle_type(make_slug, vehicle_type)
    if not make:
        raise NotFoundProblem(detail="Make not found")

    models = await model_service.get_by_make(make)
    return [FilterRead.model_validate(model_obj) for model_obj in models]
