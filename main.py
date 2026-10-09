from contextlib import asynccontextmanager

import redis
import uvicorn
from fastapi import FastAPI, APIRouter
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from fastapi_problem.handler import new_exception_handler, add_exception_handler

from config import settings
from routers.health import health_router
from routers.v1.filters import filters_router
from routers.v1.lots import cars_router
from routers.v1.history_lots import history_cars_router
from routers.v1.sales_history import sales_history_router
from routers.v1.similar_archived_sales import similar_sales_router
from routers.v1.sitemaps import sitemaps_router
from routers.v1.title_indicators import title_indicators_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.Redis.from_url(settings.REDIS_URL)
    FastAPICache.init(RedisBackend(redis_client), prefix="fastapi-cache")
    yield


docs_url = "/docs" if settings.enable_docs else None
redoc_url = "/redoc"  if settings.enable_docs else None
openapi_url = "/openapi.json" if settings.enable_docs else None
app = FastAPI(lifespan=lifespan,
              root_path=settings.ROOT_PATH,
              title="Auction Api Service",
              description="IAAI COPART Auctions API",
              version="0.0.1",
              docs_url=docs_url,
              redoc_url=redoc_url,
              openapi_url=openapi_url,
              )

eh = new_exception_handler()
add_exception_handler(app, eh)


public_v1_router = APIRouter(prefix="/public/v1")

public_v1_router.include_router(cars_router, prefix='/lot/current', tags=["Public Current Lots"])
public_v1_router.include_router(history_cars_router, prefix='/lot/history', tags=["Public History Lots"])

public_v1_router.include_router(filters_router, prefix='/filters', tags=["Filters"])

public_v1_router.include_router(sales_history_router, prefix='/lot/sales-history', tags=["Sales History"])

public_v1_router.include_router(similar_sales_router, prefix='/lot/similar-sales', tags=["Similar Sales"])

public_v1_router.include_router(title_indicators_router, prefix='/lot/title-indicators', tags=["Title Indicators"])

public_v1_router.include_router(sitemaps_router, prefix='/sitemaps', tags=["Sitemaps"])
app.include_router(public_v1_router)

app.include_router(health_router, tags=["Health"])



if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8001)




