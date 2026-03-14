# pylint: disable=protected-access
from unittest.mock import MagicMock
from uuid import uuid4

from memiris.domain.memory_connection import ConnectionType, MemoryConnection


def test_run_sleep_uses_historical_duplicates_when_no_unslept(build_sleeper) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memory_id_a = uuid4()
    memory_id_b = uuid4()
    historical_duplicates = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_id_a, memory_id_b],
        )
    ]

    sleeper.memory_repository.find_unslept_memories.return_value = []
    sleeper._load_active_duplicate_connections = MagicMock(  # type: ignore[method-assign]
        return_value=historical_duplicates
    )
    sleeper._data_caching = MagicMock()  # type: ignore[method-assign]
    sleeper._deduplicate_memories = MagicMock()  # type: ignore[method-assign]

    sleeper.run_sleep(tenant)

    sleeper.memory_repository.save_all.assert_not_called()
    sleeper._load_active_duplicate_connections.assert_called_once_with(tenant)
    sleeper._data_caching.assert_called_once_with(historical_duplicates, tenant)
    sleeper._deduplicate_memories.assert_called_once_with(historical_duplicates, tenant)


def test_run_sleep_marks_unslept_memories_slept_then_runs_historical_dedup(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    unslept_a = make_memory(uuid4(), slept_on=False)
    unslept_b = make_memory(uuid4(), slept_on=False)

    sleeper.memory_repository.find_unslept_memories.return_value = [
        unslept_a,
        unslept_b,
    ]
    sleeper._general_cleanup = MagicMock(return_value=[unslept_a, unslept_b])  # type: ignore[method-assign]
    sleeper._create_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._save_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]

    historical_duplicates = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[unslept_a.id, unslept_b.id],  # type: ignore[list-item]
        )
    ]
    sleeper._load_active_duplicate_connections = MagicMock(  # type: ignore[method-assign]
        return_value=historical_duplicates
    )
    sleeper._data_caching = MagicMock()  # type: ignore[method-assign]
    sleeper._deduplicate_memories = MagicMock()  # type: ignore[method-assign]

    sleeper.run_sleep(tenant)

    assert unslept_a.slept_on is True
    assert unslept_b.slept_on is True
    sleeper.memory_repository.save_all.assert_called_once_with(
        tenant, [unslept_a, unslept_b]
    )
    sleeper._data_caching.assert_called_once_with(historical_duplicates, tenant)
    sleeper._deduplicate_memories.assert_called_once_with(historical_duplicates, tenant)


def test_run_sleep_skips_dedup_when_no_active_duplicate_connections(
    build_sleeper,
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    sleeper.memory_repository.find_unslept_memories.return_value = []
    sleeper._load_active_duplicate_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._data_caching = MagicMock()  # type: ignore[method-assign]
    sleeper._deduplicate_memories = MagicMock()  # type: ignore[method-assign]

    sleeper.run_sleep(tenant)

    sleeper._data_caching.assert_not_called()
    sleeper._deduplicate_memories.assert_not_called()


def test_run_sleep_continues_when_cleanup_removes_all_recent_memories(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    recent = [make_memory(uuid4(), slept_on=False)]
    historical_duplicates = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[uuid4(), uuid4()],
        )
    ]

    sleeper.memory_repository.find_unslept_memories.return_value = recent
    sleeper._general_cleanup = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._create_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._save_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._load_active_duplicate_connections = MagicMock(  # type: ignore[method-assign]
        return_value=historical_duplicates
    )
    sleeper._data_caching = MagicMock()  # type: ignore[method-assign]
    sleeper._deduplicate_memories = MagicMock()  # type: ignore[method-assign]

    sleeper.run_sleep(tenant)

    sleeper._create_memory_connections.assert_called_once_with([])
    sleeper.memory_repository.save_all.assert_called_once_with(tenant, [])
    sleeper._data_caching.assert_called_once_with(historical_duplicates, tenant)
    sleeper._deduplicate_memories.assert_called_once_with(historical_duplicates, tenant)


def test_run_sleep_forwards_kwargs_to_connection_and_dedup(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"
    custom_kwargs = {"trace_id": "abc-123", "dry_run": True}

    recent = [make_memory(uuid4(), slept_on=False)]
    sleeper.memory_repository.find_unslept_memories.return_value = recent
    sleeper._general_cleanup = MagicMock(return_value=recent)  # type: ignore[method-assign]
    sleeper._create_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._save_memory_connections = MagicMock(return_value=[])  # type: ignore[method-assign]
    sleeper._load_active_duplicate_connections = MagicMock(  # type: ignore[method-assign]
        return_value=[
            MemoryConnection(
                connection_type=ConnectionType.DUPLICATE,
                memories=[uuid4(), uuid4()],
            )
        ]
    )
    sleeper._data_caching = MagicMock()  # type: ignore[method-assign]
    sleeper._deduplicate_memories = MagicMock()  # type: ignore[method-assign]

    sleeper.run_sleep(tenant, **custom_kwargs)

    create_call = sleeper._create_memory_connections.call_args
    assert create_call.args[0] == recent
    assert create_call.kwargs == custom_kwargs

    dedup_call = sleeper._deduplicate_memories.call_args
    assert dedup_call.args[1] == tenant
    assert dedup_call.kwargs == custom_kwargs
