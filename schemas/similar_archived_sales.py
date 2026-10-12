from pydantic import BaseModel


class SimilarArchivedSalesPricesOut(BaseModel):
    min_price: int | None = None
    avg_price: float | None = None
    max_price: int | None = None
    processed_lots: int = 0
