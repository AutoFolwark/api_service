from typing import Union

from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.types.search import CurrentSearchParams, HistorySearchParams
from core.logger import logger
from database.crud.car_make import MakeService
from database.crud.car_model import ModelService
from database.crud.damage import DamageService
from database.crud.document import DocumentService
from database.crud.drive import DriveService
from database.crud.status import StatusService
from database.crud.transmission import TransmissionService
from database.crud.vehicle_type import VehicleTypeService


async def transform_slugs(
    data: Union[HistorySearchParams, CurrentSearchParams], db: AsyncSession
) -> Union[HistorySearchParams, CurrentSearchParams]:
    field_service_map = {
        "make": MakeService,
        "model": ModelService,
        "vehicle_type": VehicleTypeService,
        "transmission": TransmissionService,
        "status": StatusService,
        "drive": DriveService,
        "damage_pr": DamageService,
        "document": DocumentService,
    }

    data_dict = data.model_dump()

    for field_name, field_value in data_dict.items():
        service_class = field_service_map.get(field_name)
        if not service_class or field_value in (None, "", [], ()):
            continue

        service = service_class(db)
        is_list = isinstance(field_value, (list, tuple, set))
        values = list(field_value) if is_list else [field_value]

        transformed = []
        for value in values:
            try:
                obj = await service.get_by_field("slug", value)
                transformed.append(obj.name if obj else value)
            except Exception as e:
                logger.exception(
                    f"Error while transforming slugs for {field_name}",
                    exception=e.__str__(),
                )
                transformed.append(value)

        setattr(data, field_name, transformed if is_list else transformed[0])

    logger.debug(f"Transformed slugs: {data}")
    return data
