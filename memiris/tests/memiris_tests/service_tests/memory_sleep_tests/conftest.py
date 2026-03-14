# pylint: disable=missing-class-docstring
from collections.abc import Callable
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from memiris.domain.memory import Memory
from memiris.domain.memory_connection import MemoryConnection
from memiris.service.memory_sleep import MemorySleeper


class MemorySleeperTestAdapter(MemorySleeper):
    def load_active_duplicate_connections_for_test(
        self, tenant: str
    ) -> list[MemoryConnection]:
        return self._load_active_duplicate_connections(tenant)

    def data_caching_for_test(
        self, duplicate_connections: list[MemoryConnection], tenant: str
    ) -> None:
        self._data_caching(duplicate_connections, tenant)

    def deduplicate_memories_for_test(
        self, connections: list[MemoryConnection], tenant: str
    ) -> list[Memory]:
        return self._deduplicate_memories(connections, tenant)

    def general_cleanup_for_test(
        self, tenant: str, memories: list[Memory]
    ) -> list[Memory]:
        return self._general_cleanup(tenant, memories)


@pytest.fixture
def build_sleeper() -> Callable[[], MemorySleeperTestAdapter]:
    def _build() -> MemorySleeperTestAdapter:
        sleeper = object.__new__(MemorySleeperTestAdapter)
        sleeper.memory_repository = MagicMock()
        sleeper.memory_connection_repository = MagicMock()
        sleeper.learning_repository = MagicMock()
        sleeper.vectorizer = MagicMock()
        sleeper.langfuse_client = MagicMock()
        sleeper.memory_cache = {}
        sleeper.learning_cache = {}
        sleeper.max_threads = 1
        sleeper.group_size = 20
        sleeper.max_groups = 5
        return sleeper

    return _build


@pytest.fixture
def make_memory() -> Callable[..., Memory]:
    def _make(
        memory_id: UUID,
        *,
        deleted: bool = False,
        learnings: list[UUID] | None = None,
        slept_on: bool = False,
    ) -> Memory:
        return Memory(
            uid=memory_id,
            title=f"Memory-{memory_id}",
            content="content",
            learnings=learnings or [],
            deleted=deleted,
            slept_on=slept_on,
        )

    return _make
