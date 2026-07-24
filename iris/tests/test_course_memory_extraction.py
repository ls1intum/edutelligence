from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.config import settings
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


def _mock_chain(mock_prompt, response: str):
    chain = MagicMock()
    chain.invoke.return_value = response
    mock_prompt.from_messages.return_value.__or__ = MagicMock(return_value=chain)


def test_extract_qa_falls_back_to_root_post_when_parse_fails_for_correction():
    dto = SimpleNamespace(
        thread=[ThreadMessageDTO(id="1", authorRole="student", content="Why is X?")],
        source=CourseMemorySource.IRIS_CORRECTED,
        existing_answer="The corrected answer.",
        message_id="m1",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    with patch(
        "iris.pipeline.course_memory_ingestion_pipeline.ChatPromptTemplate"
    ) as mock_prompt:
        _mock_chain(mock_prompt, "not json at all")
        pipeline.pipeline = MagicMock()

        question, answer = pipeline.extract_qa()

    # The tutor's answer is already at hand; a malformed extraction must not
    # fail the correction. The thread's root post serves as the question.
    assert question == "Why is X?"
    assert answer == "The corrected answer."


def test_extract_qa_still_raises_on_parse_failure_for_non_correction():
    dto = SimpleNamespace(
        thread=[ThreadMessageDTO(id="1", authorRole="student", content="Why?")],
        source=CourseMemorySource.THREAD_RESOLVED,
        existing_answer=None,
        message_id="m1",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    with patch(
        "iris.pipeline.course_memory_ingestion_pipeline.ChatPromptTemplate"
    ) as mock_prompt:
        _mock_chain(mock_prompt, "not json at all")
        pipeline.pipeline = MagicMock()

        with pytest.raises(ValueError):
            pipeline.extract_qa()


def test_format_thread_keeps_root_post_on_truncation(monkeypatch):
    monkeypatch.setattr(settings.course_memory, "context_message_limit", 5)
    messages = [
        ThreadMessageDTO(id=str(i), authorRole="student", content=f"msg-{i}")
        for i in range(30)
    ]
    pipeline = _pipeline_with_mocked_llm(SimpleNamespace(thread=messages))

    lines = pipeline._format_thread().split("\n")

    # Root post (the original question) plus the most recent tail.
    assert len(lines) == 5
    assert "msg-0" in lines[0]
    assert "msg-26" in lines[1]
    assert "msg-29" in lines[-1]
