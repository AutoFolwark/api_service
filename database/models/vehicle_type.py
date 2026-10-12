from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, relationship

from database.models import Base
from database.models.base_filter_mixin import BaseFilterMixin

if TYPE_CHECKING:
    from database.models.car_make import Make


class VehicleType(BaseFilterMixin, Base):
    __tablename__ = "vehicle_type"

    makes: Mapped[list["Make"]] = relationship(
        "Make", back_populates="vehicle_type", lazy="selectin"
    )
