import hashlib
import json
from typing import Any, Optional

import redis

from core.logger import logger


class RedisCache:
    def __init__(self, redis_client: redis.Redis):
        self.client = redis_client

    async def get(self, key: str) -> Optional[Any]:
        try:
            data = await self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Redis get error for key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        try:
            await self.client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as e:
            logger.warning(f"Redis set error for key {key}: {e}")

    async def delete(self, key: str) -> None:
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.warning(f"Redis delete error for key {key}: {e}")

    async def delete_pattern(self, pattern: str) -> None:
        try:
            cursor = b"0"
            while cursor:
                cursor, keys = await self.client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    await self.client.delete(*keys)
                if cursor == b"0":
                    break
        except Exception as e:
            logger.warning(f"Redis delete pattern error for {pattern}: {e}")


class CacheKeyBuilder:
    @staticmethod
    def lot_by_id(lot_id: int, site: str | None = None) -> str:
        site_part = f":{site}" if site else ""
        return f"lot:id:{lot_id}{site_part}"

    @staticmethod
    def lot_by_vin_or_id(vin_or_lot: str, site: str | None = None) -> str:
        site_part = f":{site}" if site else ""
        return f"lot:vin_or_id:{vin_or_lot}{site_part}"

    @staticmethod
    def current_bid(lot_id: int, site: str | None = None) -> str:
        site_part = f":{site}" if site else ""
        return f"bid:current:{lot_id}{site_part}"

    @staticmethod
    def sale_history(lot_id: int, site: str | None = None) -> str:
        site_part = f":{site}" if site else ""
        return f"history:sale:{lot_id}{site_part}"

    @staticmethod
    def current_lots(**filters) -> str:
        if filters:
            filter_json = json.dumps(filters, sort_keys=True)
            filter_md5 = hashlib.md5(filter_json.encode("utf-8")).hexdigest()
            return f"lots:current:{filter_md5}"
        return "lots:current:all"

    @staticmethod
    def average_price(**filters) -> str:
        if filters:
            filter_json = json.dumps(filters, sort_keys=True)
            filter_md5 = hashlib.md5(filter_json.encode("utf-8")).hexdigest()
            return f"average_price:{filter_md5}"
        return "average_price:without_filter"
