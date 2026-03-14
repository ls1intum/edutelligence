from uuid import uuid4

from memiris.domain.learning import Learning
from memiris.domain.memory_connection import ConnectionType, MemoryConnection


def test_data_caching_skips_deleted_memories_and_only_fetches_active_learnings(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    keep_learning = uuid4()
    deleted_learning = uuid4()

    active_memory = make_memory(uuid4(), learnings=[keep_learning])
    deleted_memory = make_memory(uuid4(), deleted=True, learnings=[deleted_learning])

    sleeper.memory_repository.find_by_ids.return_value = [active_memory, deleted_memory]
    sleeper.learning_repository.find_by_ids.return_value = [
        Learning(
            uid=keep_learning,
            title="L1",
            content="learning",
            reference="ref",
        )
    ]

    duplicate_connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[active_memory.id, deleted_memory.id],  # type: ignore[list-item]
        )
    ]

    sleeper.data_caching_for_test(duplicate_connections, tenant)

    assert active_memory.id in sleeper.memory_cache
    assert deleted_memory.id not in sleeper.memory_cache

    args = sleeper.learning_repository.find_by_ids.call_args.args
    assert args[0] == tenant
    assert set(args[1]) == {keep_learning}


def test_data_caching_does_not_fetch_learnings_when_no_active_memories(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    deleted_memory = make_memory(uuid4(), deleted=True, learnings=[uuid4()])
    sleeper.memory_repository.find_by_ids.return_value = [deleted_memory]

    duplicate_connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[deleted_memory.id],  # type: ignore[list-item]
        )
    ]

    sleeper.data_caching_for_test(duplicate_connections, tenant)

    sleeper.learning_repository.find_by_ids.assert_not_called()
    assert sleeper.memory_cache == {}


def test_data_caching_fetches_unique_learning_ids_once(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    shared_learning = uuid4()
    other_learning = uuid4()

    memory_a = make_memory(uuid4(), learnings=[shared_learning, other_learning])
    memory_b = make_memory(uuid4(), learnings=[shared_learning])

    sleeper.memory_repository.find_by_ids.return_value = [memory_a, memory_b]
    sleeper.learning_repository.find_by_ids.return_value = []

    connections = [
        MemoryConnection(
            connection_type=ConnectionType.DUPLICATE,
            memories=[memory_a.id, memory_b.id],  # type: ignore[list-item]
        )
    ]

    sleeper.data_caching_for_test(connections, tenant)

    learning_call = sleeper.learning_repository.find_by_ids.call_args
    assert learning_call.args[0] == tenant
    assert set(learning_call.args[1]) == {shared_learning, other_learning}


def test_data_caching_noops_for_empty_connection_list(build_sleeper) -> None:
    sleeper = build_sleeper()

    sleeper.data_caching_for_test([], "tenant-a")

    sleeper.memory_repository.find_by_ids.assert_not_called()
    sleeper.learning_repository.find_by_ids.assert_not_called()
