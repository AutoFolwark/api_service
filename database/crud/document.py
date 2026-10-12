from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.document import Document
from database.schemas.filters import FilterCreate, FilterUpdate


class DocumentService(BaseService[Document, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Document, session)
