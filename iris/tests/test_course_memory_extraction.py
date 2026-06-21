from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.data.thread_message_dto import ThreadMessageDTO
from iris.pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryIngestionPipeline,
)

# pylint: disable=protected-access


def test_parse_extraction_plain_json():
    q, a = CourseMemoryIngestionPipeline._parse_extraction(
        '{"question": "What is X?", "answer": "X is Y."}'
    )
    assert q == "What is X?"
    assert a == "X is Y."


def test_parse_extraction_fenced_json():
    fenced = '```json\n{"question": "Q?", "answer": "A."}\n```'
    q, a = CourseMemoryIngestionPipeline._parse_extraction(fenced)
    assert q == "Q?"
    assert a == "A."


def test_parse_extraction_raises_on_malformed():
    with pytest.raises(ValueError):
        CourseMemoryIngestionPipeline._parse_extraction("not json at all")


def test_parse_extraction_raises_on_empty_fields():
    with pytest.raises(ValueError):
        CourseMemoryIngestionPipeline._parse_extraction(
            '{"question": "", "answer": "A"}'
        )


def _pipeline_with_mocked_llm(dto):
    pipeline = object.__new__(CourseMemoryIngestionPipeline)
    pipeline.dto = dto
    pipeline.tokens = []
    pipeline.llm = SimpleNamespace(tokens=None)
    return pipeline


def test_extract_qa_uses_existing_answer_for_corrections():
    dto = SimpleNamespace(
        thread=[ThreadMessageDTO(id="1", authorRole="student", content="why?")],
        source=CourseMemorySource.IRIS_CORRECTED,
        existing_answer="The corrected answer.",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    with patch(
        "iris.pipeline.course_memory_ingestion_pipeline.ChatPromptTemplate"
    ) as mock_prompt:
        chain = MagicMock()
        chain.invoke.return_value = (
            '{"question": "Why?", "answer": "ignored extracted"}'
        )
        mock_prompt.from_messages.return_value.__or__ = MagicMock(return_value=chain)
        # pipeline.pipeline is referenced via (prompt | self.pipeline)
        pipeline.pipeline = MagicMock()

        question, answer = pipeline.extract_qa()

    assert question == "Why?"
    assert answer == "The corrected answer."
