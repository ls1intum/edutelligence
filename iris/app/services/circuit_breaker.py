import logging
from enum import Enum
from app.services.cache import cache_store

log = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker pattern."""

    MAX_FAILURES = 3
    CLOSED_TTL_SECONDS = 300
    OPEN_TTL_SECONDS = 30

    class Status(str, Enum):
        OPEN = "OPEN"
        CLOSED = "CLOSED"

    @classmethod
    def protected_call(
        cls, func, cache_key: str, accepted_exceptions: tuple = ()
    ):
        """Wrap function call to avoid too many failures in a row.

        Params:
            func: function to be called
            cache_key: key to be used in the cache store
            accepted_exceptions: exceptions that are not considered failures

        Raises:
            ValueError: if within the last OPEN_TTL_SECONDS seconds,
            the function throws an exception for the MAX_FAILURES-th time.
        """

        num_failures_key = f"{cache_key}:num_failures"
        status_key = f"{cache_key}:status"

        status = cache_store.get(status_key)
        if status == cls.Status.OPEN:
            raise ValueError("Too many failures! Please try again later.")

        try:
            response = func()
            cache_store.set(
                status_key, cls.Status.CLOSED, ex=cls.CLOSED_TTL_SECONDS
            )
            return response
        except accepted_exceptions as e:
            raise e
        except Exception as e:
            cls.handle_exception(e, num_failures_key, status_key)

    @classmethod
    async def protected_call_async(
        cls, func, cache_key: str, accepted_exceptions: tuple = ()
    ):
        """Wrap function call to avoid too many failures in a row.
        Async version.

        Params:
            func: function to be called
            cache_key: key to be used in the cache store
            accepted_exceptions: exceptions that are not considered failures

        Raises:
            ValueError: if within the last OPEN_TTL_SECONDS seconds,
            the function throws an exception for the MAX_FAILURES-th time.
        """

        num_failures_key = f"{cache_key}:num_failures"
        status_key = f"{cache_key}:status"

        status = cache_store.get(status_key)
        if status == cls.Status.OPEN:
            raise ValueError("Too many failures! Please try again later.")

        try:
            response = await func()
            cache_store.set(
                status_key, cls.Status.CLOSED, ex=cls.CLOSED_TTL_SECONDS
            )
            return response
        except accepted_exceptions as e:
            log.error("Accepted error in protected_call for " + cache_key)
            raise e
        except Exception as e:
            cls.handle_exception(e, num_failures_key, status_key)

    @classmethod
    def handle_exception(cls, e, num_failures_key, status_key):
        num_failures = cache_store.incr(num_failures_key)
        cache_store.expire(num_failures_key, cls.OPEN_TTL_SECONDS)
        if num_failures >= cls.MAX_FAILURES:
            cache_store.set(
                status_key, cls.Status.OPEN, ex=cls.OPEN_TTL_SECONDS
            )
        raise e

    @classmethod
    def get_status(cls, checkhealth_func, cache_key: str):
        """Get the status of the cache_key.
        If the key is not in the cache, performs the function call.
        Otherwise, returns the cached value.

        Params:
            checkhealth_func: function to be called. Only returns a boolean.
            cache_key: key to be used in the cache store

        Returns: Status of the cache_key.
        Circuit is CLOSED if cache_key is up and running, and OPEN otherwise.
        """
        status_key = f"{cache_key}:status"
        status = cache_store.get(status_key)

        if status:
            return cls.Status(status)

        is_up = False
        try:
            is_up = checkhealth_func()
        except Exception as e:
            log.error(e)

        if is_up:
            cache_store.set(
                status_key, cls.Status.CLOSED, ex=cls.CLOSED_TTL_SECONDS
            )
            return cls.Status.CLOSED

        cache_store.set(status_key, cls.Status.OPEN, ex=cls.OPEN_TTL_SECONDS)
        return cls.Status.OPEN
