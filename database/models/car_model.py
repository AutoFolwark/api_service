from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base
from database.models.base_filter_mixin import BaseFilterMixin

if TYPE_CHECKING:
    from database.models.car_make import Make


class Model(BaseFilterMixin, Base):
    __tablename__ = "model"

    slug: Mapped[str] = mapped_column(unique=False, index=True)

    make_id: Mapped[int] = mapped_column(
        ForeignKey("make.id", ondelete="CASCADE"), nullable=False
    )
    make: Mapped["Make"] = relationship("Make", back_populates="models")
