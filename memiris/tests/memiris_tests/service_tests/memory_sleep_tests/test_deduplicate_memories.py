# pylint: disable=protected-access
from unittest.mock import MagicMock
from uuid import uuid4

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.domain.memory_connection import ConnectionType, MemoryConnection


def test_deduplicate_memories_returns_empty_for_no_connections(build_sleeper) -> None:
    sleeper = build_sleeper()

    result = sleeper.deduplicate_memories_for_test([], tenant="tenant-a")

    assert result == []


def test_deduplicate_memories_ignores_non_duplicate_connections(build_sleeper) -> None:
    sleeper = build_sleeper()

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.RELATED,
            memories=[uuid4(), uuid4()],
        )
    ]

    result = sleeper.deduplicate_memories_for_test(connections, tenant="tenant-a")

    assert result == []


def test_deduplicate_memories_skips_connections_with_less_than_two_active_memories(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()

    memory_id = uuid4()
    sleeper.memory_cache[memory_id] = make_memory(memory_id, deleted=False)

    process_group_mock = MagicMock(return_value=([], []))
    sleeper._process_memory_group_for_deduplication = process_group_mock  # type: ignore[method-assign]

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_id],
        )
    ]

    result = sleeper.deduplicate_memories_for_test(connections, tenant="tenant-a")

    assert result == []
    process_group_mock.assert_not_called()


def test_deduplicate_memories_builds_groups_with_only_cached_learnings(
    build_sleeper,
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memory_a_id = uuid4()
    memory_b_id = uuid4()
    learning_keep = uuid4()
    learning_missing = uuid4()

    sleeper.memory_cache[memory_a_id] = Memory(
        uid=memory_a_id,
        title="A",
        content="a",
        learnings=[learning_keep, learning_missing],
    )
    sleeper.memory_cache[memory_b_id] = Memory(
        uid=memory_b_id,
        title="B",
        content="b",
        learnings=[learning_keep],
    )
    sleeper.learning_cache[learning_keep] = Learning(
        uid=learning_keep,
        title="L",
        content="learning",
        reference="ref",
    )

    process_group_mock = MagicMock(return_value=([], []))
    sleeper._process_memory_group_for_deduplication = process_group_mock  # type: ignore[method-assign]

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_a_id, memory_b_id],
        )
    ]

    deduplicated = sleeper.deduplicate_memories_for_test(connections, tenant)

    assert deduplicated == []
    process_group_mock.assert_called_once()

    memory_group = process_group_mock.call_args.args[0]
    assert len(memory_group) == 2
    for memory_input in memory_group:
        assert [learning.id for learning in memory_input.learnings] == [learning_keep]


def test_deduplicate_memories_saves_memories_and_created_from_connections(
    build_sleeper,
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memory_a_id = uuid4()
    memory_b_id = uuid4()
    learning_id = uuid4()

    sleeper.memory_cache[memory_a_id] = Memory(
        uid=memory_a_id,
        title="A",
        content="a",
        learnings=[learning_id],
    )
    sleeper.memory_cache[memory_b_id] = Memory(
        uid=memory_b_id,
        title="B",
        content="b",
        learnings=[learning_id],
    )
    sleeper.learning_cache[learning_id] = Learning(
        uid=learning_id,
        title="L",
        content="learning",
        reference="ref",
    )

    saved_memory = Memory(
        uid=uuid4(),
        title="Merged",
        content="merged-content",
        learnings=[learning_id],
        slept_on=True,
    )
    created_from_connection = MemoryConnection(
        uid=uuid4(),
        connection_type=ConnectionType.CREATED_FROM,
        memories=[memory_a_id, memory_b_id],
    )

    sleeper._process_memory_group_for_deduplication = MagicMock(  # type: ignore[method-assign]
        return_value=([saved_memory], [created_from_connection])
    )
    sleeper.memory_repository.save_all.return_value = [saved_memory]
    sleeper.memory_connection_repository.save_all.return_value = [
        created_from_connection
    ]

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_a_id, memory_b_id],
        )
    ]

    result = sleeper.deduplicate_memories_for_test(connections, tenant)

    assert result == [saved_memory]
    sleeper.memory_repository.save_all.assert_called_once_with(tenant, [saved_memory])
    sleeper.memory_connection_repository.save_all.assert_called_once_with(
        tenant, [created_from_connection]
    )


def test_deduplicate_memories_normalizes_duplicate_memory_ids_before_grouping(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()

    memory_a_id = uuid4()
    memory_b_id = uuid4()
    learning_id = uuid4()

    sleeper.memory_cache[memory_a_id] = make_memory(
        memory_a_id, learnings=[learning_id]
    )
    sleeper.memory_cache[memory_b_id] = make_memory(
        memory_b_id, learnings=[learning_id]
    )
    sleeper.learning_cache[learning_id] = Learning(
        uid=learning_id,
        title="L",
        content="learning",
        reference="ref",
    )

    process_group_mock = MagicMock(return_value=([], []))
    sleeper._process_memory_group_for_deduplication = process_group_mock  # type: ignore[method-assign]

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_a_id, memory_a_id, memory_b_id],
        )
    ]

    sleeper.deduplicate_memories_for_test(connections, tenant="tenant-a")

    grouped = process_group_mock.call_args.args[0]
    assert [item.id for item in grouped] == [memory_a_id, memory_b_id]


def test_deduplicate_memories_does_not_save_when_all_groups_return_empty(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()

    memory_a_id = uuid4()
    memory_b_id = uuid4()
    learning_id = uuid4()

    sleeper.memory_cache[memory_a_id] = make_memory(
        memory_a_id, learnings=[learning_id]
    )
    sleeper.memory_cache[memory_b_id] = make_memory(
        memory_b_id, learnings=[learning_id]
    )
    sleeper.learning_cache[learning_id] = Learning(
        uid=learning_id,
        title="L",
        content="learning",
        reference="ref",
    )

    sleeper._process_memory_group_for_deduplication = MagicMock(  # type: ignore[method-assign]
        return_value=([], [])
    )

    result = sleeper.deduplicate_memories_for_test(
        [
            MemoryConnection(
                connection_type=ConnectionType.DUPLICATE,
                memories=[memory_a_id, memory_b_id],
            )
        ],
        tenant="tenant-a",
    )

    assert result == []
    sleeper.memory_repository.save_all.assert_not_called()
    sleeper.memory_connection_repository.save_all.assert_not_called()


def test_deduplicate_memories_updates_cache_for_saved_memories_and_connections(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memory_a_id = uuid4()
    memory_b_id = uuid4()
    learning_id = uuid4()

    sleeper.memory_cache[memory_a_id] = make_memory(
        memory_a_id, learnings=[learning_id]
    )
    sleeper.memory_cache[memory_b_id] = make_memory(
        memory_b_id, learnings=[learning_id]
    )
    sleeper.learning_cache[learning_id] = Learning(
        uid=learning_id,
        title="L",
        content="learning",
        reference="ref",
    )

    deleted_saved = make_memory(memory_a_id, deleted=True, learnings=[learning_id])
    kept_saved = make_memory(uuid4(), learnings=[learning_id], slept_on=True)

    created_from = MemoryConnection(
        uid=uuid4(),
        connection_type=ConnectionType.CREATED_FROM,
        memories=[memory_b_id],
    )

    sleeper._process_memory_group_for_deduplication = MagicMock(  # type: ignore[method-assign]
        return_value=([deleted_saved, kept_saved], [created_from])
    )
    sleeper.memory_repository.save_all.return_value = [deleted_saved, kept_saved]
    sleeper.memory_connection_repository.save_all.return_value = [created_from]

    result = sleeper.deduplicate_memories_for_test(
        [
            MemoryConnection(
                connection_type=ConnectionType.DUPLICATE,
                memories=[memory_a_id, memory_b_id],
            )
        ],
        tenant,
    )

    assert result == [deleted_saved, kept_saved]
    assert sleeper.memory_cache[memory_a_id].deleted is True
    assert kept_saved.id in sleeper.memory_cache
    assert created_from.id in sleeper.memory_cache[memory_b_id].connections
