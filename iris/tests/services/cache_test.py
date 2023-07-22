import pytest
from datetime import datetime
from freezegun import freeze_time
from app.services.cache import HazelcastCacheStore, InMemoryCacheStore


@pytest.fixture(scope="function")
def in_memory_cache():
    return InMemoryCacheStore()


@pytest.fixture(scope="function")
def hazelcast_cache():
    return HazelcastCacheStore()


class TestInMemoryCacheStore:
    def test_set_and_get(self, in_memory_cache):
        in_memory_cache.set("test_key", "test_value")
        assert in_memory_cache.get("test_key") == "test_value"
        assert in_memory_cache._cache["test_key"].expired_at is None

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_set_and_get_an_existing_key(self, in_memory_cache):
        in_memory_cache.set("test_key", "test_value", ex=30)
        assert in_memory_cache.get("test_key") == "test_value"
        assert in_memory_cache._cache["test_key"].expired_at == datetime(
            year=2023, month=6, day=16, hour=1, minute=22, second=4
        )

        in_memory_cache.set("test_key", "test_value2")
        assert in_memory_cache.get("test_key") == "test_value2"
        assert in_memory_cache._cache["test_key"].expired_at is None

    def test_set_and_get_before_expired_time(self, in_memory_cache):
        initial_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=3
        )
        other_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=34
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            in_memory_cache.set("test_key", "test_value", ex=40)
            assert in_memory_cache.get("test_key") == "test_value"
            assert in_memory_cache._cache["test_key"].expired_at == datetime(
                year=1, month=1, day=1, hour=15, minute=2, second=43
            )

            frozen_datetime.move_to(other_datetime)

            assert in_memory_cache.get("test_key") == "test_value"
            assert in_memory_cache._cache["test_key"].expired_at == datetime(
                year=1, month=1, day=1, hour=15, minute=2, second=43
            )

    def test_set_and_get_after_expired_time(self, in_memory_cache):
        initial_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=3
        )
        other_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=34
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            in_memory_cache.set("test_key", "test_value", ex=30)
            assert in_memory_cache.get("test_key") == "test_value"
            assert in_memory_cache._cache["test_key"].expired_at == datetime(
                year=1, month=1, day=1, hour=15, minute=2, second=33
            )

            frozen_datetime.move_to(other_datetime)

            assert in_memory_cache.get("test_key") is None
            assert "test_key" not in in_memory_cache._cache

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_expire_a_existing_key(self, in_memory_cache):
        in_memory_cache.set("test_key", "test_value")
        in_memory_cache.expire("test_key", 30)
        assert in_memory_cache._cache["test_key"].expired_at == datetime(
            year=2023, month=6, day=16, hour=1, minute=22, second=4
        )

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_expire_a_non_existing_key(self, in_memory_cache):
        in_memory_cache.expire("test_key", 30)
        assert "test_key" not in in_memory_cache._cache

    def test_incr_a_non_existing_key(self, in_memory_cache):
        response = in_memory_cache.incr("test_key")
        assert response == 1
        assert in_memory_cache.get("test_key") == 1

    def test_incr_a_existing_key(self, in_memory_cache):
        in_memory_cache.set("test_key", 1)
        response = in_memory_cache.incr("test_key")
        assert response == 2
        assert in_memory_cache.get("test_key") == 2

    def test_incr_a_existing_key_not_a_number(self, in_memory_cache):
        in_memory_cache.set("test_key", "not a number")

        with pytest.raises(TypeError, match="value is not an integer"):
            in_memory_cache.incr("test_key")

    def test_flushdb(self, in_memory_cache):
        in_memory_cache.set("test_key", "test_value")
        in_memory_cache.flushdb()

        assert in_memory_cache._cache == {}

    def test_delete_a_non_existing_key(self, in_memory_cache):
        in_memory_cache.delete("test_key")

        assert in_memory_cache.get("test_key") is None
        assert "test_key" not in in_memory_cache._cache

    def test_delete_a_existing_key(self, in_memory_cache):
        in_memory_cache.set("test_key", "test_value", ex=1000)
        in_memory_cache.delete("test_key")

        assert in_memory_cache.get("test_key") is None
        assert "test_key" not in in_memory_cache._cache


class TestHazelcastCacheStore:
    def test_set_and_get(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "test_value")
        assert hazelcast_cache.get("test_key") == "test_value"

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_set_and_get_an_existing_key(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "test_value", ex=30)
        assert hazelcast_cache.get("test_key") == "test_value"

        hazelcast_cache.set("test_key", "test_value2")
        assert hazelcast_cache.get("test_key") == "test_value2"

    def test_set_and_get_before_expired_time(self, hazelcast_cache):
        initial_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=3
        )
        other_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=34
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            hazelcast_cache.set("test_key", "test_value", ex=40)
            assert hazelcast_cache.get("test_key") == "test_value"

            frozen_datetime.move_to(other_datetime)

            assert hazelcast_cache.get("test_key") == "test_value"

    def test_set_and_get_after_expired_time(self, hazelcast_cache):
        initial_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=3
        )
        other_datetime = datetime(
            year=1, month=1, day=1, hour=15, minute=2, second=34
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            hazelcast_cache.set("test_key", "test_value", ex=30)
            assert hazelcast_cache.get("test_key") == "test_value"

            frozen_datetime.move_to(other_datetime)
            # NOTE: Hazelcast doesn't expire with freezegun
            hazelcast_cache.delete("test_key")

            assert hazelcast_cache.get("test_key") is None
            assert not hazelcast_cache._cache.contains_key("test_key")

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_expire_a_existing_key(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "test_value")
        hazelcast_cache.expire("test_key", 30)

    @freeze_time("2023-06-16 03:21:34 +02:00")
    def test_expire_a_non_existing_key(self, hazelcast_cache):
        hazelcast_cache.expire("test_key", 30)
        assert not hazelcast_cache._cache.contains_key("test_key")

    def test_incr_a_non_existing_key(self, hazelcast_cache):
        response = hazelcast_cache.incr("test_key")
        assert response == 1
        assert hazelcast_cache.get("test_key") == 1

    def test_incr_a_existing_key(self, hazelcast_cache):
        hazelcast_cache.set("test_key", 1)
        response = hazelcast_cache.incr("test_key")
        assert response == 2
        assert hazelcast_cache.get("test_key") == 2

    def test_incr_a_existing_key_not_a_number(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "not a number")

        with pytest.raises(TypeError, match="value is not an integer"):
            hazelcast_cache.incr("test_key")

    def test_flushdb(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "test_value")
        hazelcast_cache.flushdb()

        assert hazelcast_cache._cache.is_empty()

    def test_delete_a_non_existing_key(self, hazelcast_cache):
        hazelcast_cache.delete("test_key")

        assert hazelcast_cache.get("test_key") is None
        assert not hazelcast_cache._cache.contains_key("test_key")

    def test_delete_a_existing_key(self, hazelcast_cache):
        hazelcast_cache.set("test_key", "test_value", ex=1000)
        hazelcast_cache.delete("test_key")

        assert hazelcast_cache.get("test_key") is None
        assert not hazelcast_cache._cache.contains_key("test_key")
