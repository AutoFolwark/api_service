import asyncio
import time
from loguru import logger as loguru_logger
import json
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional, Dict, Any


@asynccontextmanager
async def async_timer(
        process_name: str,
        logger_instance=None,
        log_start: bool = False,
        extra_data: Optional[Dict[str, Any]] = None
):
    _logger = logger_instance or logger
    _extra = extra_data or {}

    start_time = time.perf_counter()

    if log_start:
        _logger.info(f"Starting: {process_name}", **_extra)

    try:
        yield
    except Exception as e:
        end_time = time.perf_counter()
        execution_time = end_time - start_time

        _logger.error(
            f"{process_name} failed after {execution_time:.3f} sec: {str(e)}",
            execution_time=execution_time,
            process_name=process_name,
            error_type=type(e).__name__,
            **_extra
        )
        raise
    else:
        end_time = time.perf_counter()
        execution_time = end_time - start_time

        _logger.info(
            f"{process_name} completed in {execution_time:.3f} sec",
            execution_time=execution_time,
            process_name=process_name,
            **_extra
        )


class AsyncTimer:
    def __init__(
            self,
            process_name: str,
            logger_instance=None,
            log_start: bool = False,
            extra_data: Optional[Dict[str, Any]] = None
    ):
        self.process_name = process_name
        self.logger = logger_instance or logger
        self.log_start = log_start
        self.extra_data = extra_data or {}
        self.start_time = None

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        if self.log_start:
            self.logger.info(f"Starting: {self.process_name}", **self.extra_data)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        end_time = time.perf_counter()
        execution_time = end_time - self.start_time

        if exc_type:
            self.logger.error(
                f"{self.process_name} failed after {execution_time:.3f} sec: {str(exc_val)}",
                execution_time=execution_time,
                process_name=self.process_name,
                error_type=exc_type.__name__,
                **self.extra_data
            )
        else:
            self.logger.info(
                f"{self.process_name} completed in {execution_time:.3f} sec",
                execution_time=execution_time,
                process_name=self.process_name,
                **self.extra_data
            )


def log_async_execution_time(
        process_name: Optional[str] = None,
        logger_instance=None,
        extra_data: Optional[Dict[str, Any]] = None
):
    def decorator(func):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(f"Function {func.__name__} must be async")

        @wraps(func)
        async def wrapper(*args, **kwargs):
            _process_name = process_name or f"{func.__module__}.{func.__name__}"
            async with async_timer(_process_name, logger_instance, extra_data=extra_data):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


logger = loguru_logger


def truncate_log_value(value: Any, max_chars: int = 2000) -> str:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return serialized
    return f"{serialized[:max_chars]}... [truncated; {len(serialized)} characters total]"