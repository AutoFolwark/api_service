from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base
from database.models.base_filter_mixin import BaseFilterMixin

if TYPE_CHECKING:
    from database.models.car_model import Model
    from database.models.vehicle_type import VehicleType


class Make(BaseFilterMixin, Base):
    __tablename__ = "make"

    slug: Mapped[str] = mapped_column(unique=False, index=True)

    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_type.id"), nullable=False
    )
    models: Mapped[List["Model"]] = relationship("Model", back_populates="make")

    vehicle_type: Mapped["VehicleType"] = relationship(
        "VehicleType", back_populates="makes", lazy="selectin"
    )
