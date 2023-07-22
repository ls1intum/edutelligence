from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, Any
from pydantic import BaseModel
from app.services.hazelcast_client import hazelcast_client


class CacheStoreInterface(ABC):
    @abstractmethod
    def get(self, name: str) -> Any:
        """
        Get the value at key ``name``

        Returns:
            The value at key ``name``, or None if the key doesn't exist
        """
        pass

    @abstractmethod
    def set(self, name: str, value, ex: Optional[int] = None):
        """
        Set the value at key ``name`` to ``value``

        ``ex`` sets an expire flag on key ``name`` for ``ex`` seconds.
        """
        pass

    @abstractmethod
    def expire(self, name: str, ex: int):
        """
        Set an expire flag on key ``name`` for ``ex`` seconds
        """
        pass

    @abstractmethod
    def incr(self, name: str) -> int:
        """
        Increase the integer value of a key ``name`` by 1.
        If the key does not exist, it is set to 0
        before performing the operation.

        Returns:
            The value of key ``name`` after the increment

        Raises:
            TypeError: if cache value is not an integer
        """
        pass

    @abstractmethod
    def flushdb(self):
        """
        Delete all keys in the current database
        """
        pass

    @abstractmethod
    def delete(self, name: str):
        """
        Delete the key specified by ``name``
        """
        pass


class InMemoryCacheStore(CacheStoreInterface):
    class CacheValue(BaseModel):
        value: Any
        expired_at: Optional[datetime]

    def __init__(self):
        self._cache: dict[str, Optional[InMemoryCacheStore.CacheValue]] = {}

    def get(self, name: str) -> Any:
        current_time = datetime.now()
        data = self._cache.get(name)
        if data is None:
            return None
        if data.expired_at and current_time > data.expired_at:
            del self._cache[name]
            return None
        return data.value

    def set(self, name: str, value, ex: Optional[int] = None):
        self._cache[name] = InMemoryCacheStore.CacheValue(
            value=value, expired_at=None
        )
        if ex is not None:
            self.expire(name, ex)

    def expire(self, name: str, ex: int):
        current_time = datetime.now()
        expired_at = current_time + timedelta(seconds=ex)
        data = self._cache.get(name)
        if data is None:
            return
        data.expired_at = expired_at

    def incr(self, name: str) -> int:
        value = self.get(name)
        if value is None:
            self._cache[name] = InMemoryCacheStore.CacheValue(
                value=1, expired_at=None
            )
            return 1
        if isinstance(value, int):
            value += 1
            self.set(name, value)
            return value
        raise TypeError("value is not an integer")

    def flushdb(self):
        self._cache = {}

    def delete(self, name: str):
        if name in self._cache:
            del self._cache[name]


class HazelcastCacheStore(CacheStoreInterface):
    def __init__(self):
        self._cache = hazelcast_client.get_map("cache_store").blocking()

    def get(self, name: str) -> Any:
        return self._cache.get(name)

    def set(self, name: str, value, ex: Optional[int] = None):
        self._cache.put(name, value, ex)

    def expire(self, name: str, ex: int):
        self._cache.set_ttl(name, ex)

    def incr(self, name: str) -> int:
        flag = False
        value = 0
        while not flag:
            value = self._cache.get(name)
            if value is None:
                self._cache.set(name, 1)
                return 1
            if not isinstance(value, int):
                raise TypeError("value is not an integer")

            flag = self._cache.replace_if_same(name, value, value + 1)

        return value + 1

    def flushdb(self):
        self._cache.clear()

    def delete(self, name: str):
        self._cache.remove(name)


cache_store = HazelcastCacheStore()
