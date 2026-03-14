from uuid import uuid4

from memiris.domain.memory_connection import ConnectionType, MemoryConnection


def test_load_active_duplicate_connections_returns_empty_when_none(
    build_sleeper,
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    sleeper.memory_connection_repository.find_by_connection_type.return_value = []

    result = sleeper.load_active_duplicate_connections_for_test(tenant)

    assert result == []
    sleeper.memory_repository.find_by_ids.assert_not_called()


def test_load_active_duplicate_connections_filters_deleted_stale_and_duplicate_ids(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memory_a = uuid4()
    memory_b = uuid4()
    deleted_memory = uuid4()
    stale_memory = uuid4()

    duplicate_connections = [
        MemoryConnection(
            uid=uuid4(),
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_a, memory_a, deleted_memory, stale_memory, memory_b],
            description="dup",
            context={"source": "llm"},
            weight=0.9,
        ),
        MemoryConnection(
            uid=uuid4(),
            connection_type=ConnectionType.DUPLICATE,
            memories=[stale_memory],
            description="too-small-after-filter",
            weight=0.9,
        ),
    ]

    sleeper.memory_connection_repository.find_by_connection_type.return_value = (
        duplicate_connections
    )
    sleeper.memory_repository.find_by_ids.return_value = [
        make_memory(memory_a),
        make_memory(memory_b),
        make_memory(deleted_memory, deleted=True),
    ]

    filtered = sleeper.load_active_duplicate_connections_for_test(tenant)

    assert len(filtered) == 1
    assert filtered[0].connection_type == ConnectionType.DUPLICATE
    assert filtered[0].memories == [memory_a, memory_b]
    assert filtered[0].description == "dup"
    assert filtered[0].context == {"source": "llm"}
    assert filtered[0].weight == 0.9


def test_load_active_duplicate_connections_drops_connections_that_shrink_below_two_memories(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    kept_memory = uuid4()
    deleted_memory = uuid4()

    sleeper.memory_connection_repository.find_by_connection_type.return_value = [
        MemoryConnection(
            uid=uuid4(),
            connection_type=ConnectionType.DUPLICATE,
            memories=[kept_memory, deleted_memory],
        )
    ]
    sleeper.memory_repository.find_by_ids.return_value = [
        make_memory(kept_memory),
        make_memory(deleted_memory, deleted=True),
    ]

    filtered = sleeper.load_active_duplicate_connections_for_test(tenant)

    assert filtered == []


def test_load_active_duplicate_connections_queries_duplicate_type(
    build_sleeper,
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    sleeper.memory_connection_repository.find_by_connection_type.return_value = []

    sleeper.load_active_duplicate_connections_for_test(tenant)

    sleeper.memory_connection_repository.find_by_connection_type.assert_called_once_with(
        tenant, ConnectionType.DUPLICATE.value
    )
