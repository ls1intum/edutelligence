from uuid import uuid4


def test_general_cleanup_deletes_memories_without_learnings(
    build_sleeper, make_memory
) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    empty_memory = make_memory(uuid4(), learnings=[])
    valid_memory = make_memory(uuid4(), learnings=[uuid4()])

    remaining = sleeper.general_cleanup_for_test(tenant, [empty_memory, valid_memory])

    sleeper.memory_repository.delete.assert_called_once_with(tenant, empty_memory.id)
    assert remaining == [valid_memory]


def test_general_cleanup_keeps_all_valid_memories(build_sleeper, make_memory) -> None:
    sleeper = build_sleeper()
    tenant = "tenant-a"

    memories = [
        make_memory(uuid4(), learnings=[uuid4()]),
        make_memory(uuid4(), learnings=[uuid4(), uuid4()]),
    ]

    remaining = sleeper.general_cleanup_for_test(tenant, memories)

    sleeper.memory_repository.delete.assert_not_called()
    assert remaining == memories
