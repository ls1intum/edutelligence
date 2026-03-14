from typing import List
from unittest.mock import MagicMock
from uuid import uuid4

from memiris.domain.learning import Learning
from memiris.domain.memory import Memory
from memiris.service.memory_creator.memory_creator_langchain import (
    MemoryCreatorLangChain,
)


class TestableMemoryCreatorLangChain(MemoryCreatorLangChain):
    def parse_memories_from_output_for_test(
        self, output_text: str, tenant: str
    ) -> List[Memory]:
        return self._parse_memories_from_output(output_text, tenant)


def _build_creator(find_return: Learning) -> TestableMemoryCreatorLangChain:
    creator = object.__new__(TestableMemoryCreatorLangChain)
    creator.learning_repository = MagicMock()
    creator.learning_repository.find.return_value = find_return
    return creator


def test_parse_memories_recovers_extra_trailing_bracket() -> None:
    learning_id = uuid4()
    learning = Learning(
        uid=learning_id,
        title="L1",
        content="content",
        reference="ref",
    )
    creator = _build_creator(learning)

    output = (
        '[{"title":"Test","content":"Memory body","learnings":["'
        + str(learning_id)
        + '"]}]]'
    )

    memories = creator.parse_memories_from_output_for_test(output, tenant="tenant-a")

    assert len(memories) == 1
    assert memories[0].title == "Test"
    assert memories[0].learnings == [learning_id]


def test_parse_memories_recovers_from_wrapped_text() -> None:
    learning_id = uuid4()
    learning = Learning(
        uid=learning_id,
        title="L1",
        content="content",
        reference="ref",
    )
    creator = _build_creator(learning)

    output = (
        "Some explanation before JSON. "
        '[{"title":"Wrapped","content":"Memory body","learnings":["'
        + str(learning_id)
        + '"]}] trailing text'
    )

    memories = creator.parse_memories_from_output_for_test(output, tenant="tenant-a")

    assert len(memories) == 1
    assert memories[0].title == "Wrapped"


def test_parse_memories_returns_empty_for_tool_payload_object() -> None:
    learning_id = uuid4()
    learning = Learning(
        uid=learning_id,
        title="L1",
        content="content",
        reference="ref",
    )
    creator = _build_creator(learning)

    memories = creator.parse_memories_from_output_for_test(
        '{"learning_id":"50f9db80-a60d-41af-a9ca-e4fb2b51ed3f"}',
        tenant="tenant-a",
    )

    assert memories == []
