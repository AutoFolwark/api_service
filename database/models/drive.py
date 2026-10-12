from database.models import Base
from database.models.base_filter_mixin import BaseFilterMixin


class Drive(BaseFilterMixin, Base):
    __tablename__ = "drive"
