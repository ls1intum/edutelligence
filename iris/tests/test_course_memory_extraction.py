from types import SimpleNamespace
from unittest.mock import MagicMock

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


def _mock_response(pipeline, response: str):
    """Stub the LLM chain so extract_qa() returns ``response``."""
    pipeline.pipeline = MagicMock()
    pipeline.pipeline.invoke.return_value = response


def test_extract_qa_uses_existing_answer_for_corrections():
    dto = SimpleNamespace(
        thread=[ThreadMessageDTO(id="1", authorRole="student", content="why?")],
        source=CourseMemorySource.IRIS_CORRECTED,
        existing_answer="The corrected answer.",
        message_id="1",
    )
    pipeline = _pipeline_with_mocked_llm(dto)
    _mock_response(pipeline, '{"question": "Why?", "answer": "ignored extracted"}')

    question, answer = pipeline.extract_qa()

    assert question == "Why?"
    assert answer == "The corrected answer."


def test_extract_qa_falls_back_to_root_post_when_parse_fails_for_correction():
    dto = SimpleNamespace(
        thread=[ThreadMessageDTO(id="1", authorRole="student", content="Why is X?")],
        source=CourseMemorySource.IRIS_CORRECTED,
        existing_answer="The corrected answer.",
        message_id="m1",
    )
    pipeline = _pipeline_with_mocked_llm(dto)
    _mock_response(pipeline, "not json at all")

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
    _mock_response(pipeline, "not json at all")

    with pytest.raises(ValueError):
        pipeline.extract_qa()


def test_extract_qa_handles_braces_in_thread_content():
    # Code snippets with braces must not be treated as prompt-template
    # variables (regression: ChatPromptTemplate f-string parsing crashed).
    dto = SimpleNamespace(
        thread=[
            ThreadMessageDTO(
                id="1",
                authorRole="student",
                content="Why does `dict = {'a': 1}` fail in {my_func}?",
            ),
            ThreadMessageDTO(id="2", authorRole="tutor", content="Because {x}."),
        ],
        source=CourseMemorySource.THREAD_RESOLVED,
        existing_answer=None,
        message_id="2",
    )
    pipeline = _pipeline_with_mocked_llm(dto)
    _mock_response(pipeline, '{"question": "Q?", "answer": "A."}')

    question, answer = pipeline.extract_qa()

    assert (question, answer) == ("Q?", "A.")
    # The transcript (with braces intact) is passed as a human message.
    sent = pipeline.pipeline.invoke.call_args.args[0]
    assert any("{'a': 1}" in m.content for m in sent)


def test_format_thread_marks_verified_message():
    dto = SimpleNamespace(
        thread=[
            ThreadMessageDTO(id="post-1", authorRole="student", content="Q?"),
            ThreadMessageDTO(id="answer-2", authorRole="tutor", content="first answer"),
            ThreadMessageDTO(
                id="answer-3",
                authorRole="tutor",
                content="verified answer",
                isVerifiedAnswer=True,
            ),
        ],
        message_id="answer-3",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    lines = pipeline._format_thread().split("\n")

    assert "VERIFIED ANSWER" in lines[2] and "verified answer" in lines[2]
    # Only the flagged message is tagged.
    assert sum("VERIFIED ANSWER" in line for line in lines) == 1


def test_format_thread_marks_every_resolving_message():
    # Several resolving answers must all be tagged, otherwise the extractor is
    # told to ignore them ("never as the answer source") and each entry captures
    # only a fragment of the verified answer.
    dto = SimpleNamespace(
        thread=[
            ThreadMessageDTO(id="post-1", authorRole="student", content="Q?"),
            ThreadMessageDTO(
                id="answer-2", authorRole="tutor", content="part one", resolvesPost=True
            ),
            ThreadMessageDTO(id="answer-3", authorRole="student", content="chatter"),
            ThreadMessageDTO(
                id="answer-4", authorRole="tutor", content="part two", resolvesPost=True
            ),
        ],
        message_id="answer-4",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    lines = pipeline._format_thread().split("\n")

    assert sum("VERIFIED ANSWER" in line for line in lines) == 2
    assert "VERIFIED ANSWER" not in lines[0] and "VERIFIED ANSWER" not in lines[2]


def test_format_thread_ignores_id_collisions():
    # Regression: post and answer ids come from independent sequences in Artemis,
    # so a root post can share a number with one of its answers. Tagging used to
    # be derived from `id == message_id`, which tagged the student's *question*
    # as the verified answer and stored the question text as a tutor answer.
    dto = SimpleNamespace(
        thread=[
            ThreadMessageDTO(id="post-7", authorRole="student", content="the question"),
            ThreadMessageDTO(
                id="answer-7",
                authorRole="tutor",
                content="the real answer",
                isVerifiedAnswer=True,
            ),
        ],
        message_id="answer-7",
    )
    pipeline = _pipeline_with_mocked_llm(dto)

    lines = pipeline._format_thread().split("\n")

    assert "VERIFIED ANSWER" not in lines[0]
    assert "VERIFIED ANSWER" in lines[1] and "the real answer" in lines[1]


def test_format_thread_keeps_root_post_on_truncation(monkeypatch):
    monkeypatch.setattr(settings.course_memory, "context_message_limit", 5)
    messages = [
        ThreadMessageDTO(id=str(i), authorRole="student", content=f"msg-{i}")
        for i in range(30)
    ]
    pipeline = _pipeline_with_mocked_llm(
        SimpleNamespace(thread=messages, message_id="none")
    )

    lines = pipeline._format_thread().split("\n")

    # Root post (the original question) plus the most recent tail.
    assert len(lines) == 5
    assert "msg-0" in lines[0]
    assert "msg-26" in lines[1]
    assert "msg-29" in lines[-1]


def test_format_thread_retains_verified_message_when_in_middle(monkeypatch):
    monkeypatch.setattr(settings.course_memory, "context_message_limit", 3)
    messages = [
        ThreadMessageDTO(
            id=str(i),
            authorRole="student",
            content=f"msg-{i}",
            isVerifiedAnswer=(i == 10),
        )
        for i in range(30)
    ]
    pipeline = _pipeline_with_mocked_llm(
        SimpleNamespace(thread=messages, message_id="10")
    )

    lines = pipeline._format_thread().split("\n")

    # root + verified(msg-10) + most-recent tail, capped at the limit.
    assert len(lines) == 3
    assert "msg-0" in lines[0]
    assert any("msg-10" in line and "VERIFIED ANSWER" in line for line in lines)
    assert "msg-29" in lines[-1]


def test_format_thread_retains_all_resolving_messages_on_truncation(monkeypatch):
    # Truncation must never drop a flagged message: doing so silently discards
    # part of the verified answer. The flagged set wins over the limit.
    monkeypatch.setattr(settings.course_memory, "context_message_limit", 3)
    resolving = {5, 11, 17, 23}
    messages = [
        ThreadMessageDTO(
            id=str(i),
            authorRole="tutor",
            content=f"msg-{i}",
            resolvesPost=(i in resolving),
        )
        for i in range(30)
    ]
    pipeline = _pipeline_with_mocked_llm(
        SimpleNamespace(thread=messages, message_id="23")
    )

    lines = pipeline._format_thread().split("\n")

    for i in resolving:
        assert any(f"msg-{i}" in line and "VERIFIED ANSWER" in line for line in lines)
    assert "msg-0" in lines[0]
