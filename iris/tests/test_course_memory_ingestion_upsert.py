from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryIngestionPipeline,
)
from iris.vector_database.course_memory_schema import CourseMemorySchema

# pylint: disable=protected-access


def _make_pipeline(exists: bool):
    pipeline = object.__new__(CourseMemoryIngestionPipeline)
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.return_value = [0.1, 0.2]
    pipeline.collection = MagicMock()
    pipeline.collection.data.exists.return_value = exists
    pipeline.dto = SimpleNamespace(
        course_id=7,
        message_id="msg-1",
        conversation_id="conv-1",
        source=CourseMemorySource.THREAD_RESOLVED,
        verified_at=None,
        verified_by=None,
    )
    return pipeline


def test_deterministic_uuid_is_stable():
    u1 = CourseMemoryIngestionPipeline._deterministic_uuid("msg-1", 7)
    u2 = CourseMemoryIngestionPipeline._deterministic_uuid("msg-1", 7)
    u3 = CourseMemoryIngestionPipeline._deterministic_uuid("msg-2", 7)
    assert u1 == u2
    assert u1 != u3


def test_upsert_inserts_when_absent_and_embeds_only_question():
    pipeline = _make_pipeline(exists=False)

    pipeline.upsert("the question", "the answer")

    # Only the question is embedded.
    pipeline.llm_embedding.embed.assert_called_once_with("the question")
    pipeline.collection.data.insert.assert_called_once()
    pipeline.collection.data.replace.assert_not_called()

    props = pipeline.collection.data.insert.call_args.kwargs["properties"]
    assert props[CourseMemorySchema.QUESTION.value] == "the question"
    assert props[CourseMemorySchema.ANSWER.value] == "the answer"
    assert props[CourseMemorySchema.COURSE_ID.value] == 7


def test_upsert_replaces_when_present_for_correction():
    pipeline = _make_pipeline(exists=True)

    pipeline.upsert("q", "corrected answer")

    pipeline.collection.data.replace.assert_called_once()
    pipeline.collection.data.insert.assert_not_called()


def test_non_public_channel_short_circuits_without_writing():
    pipeline = _make_pipeline(exists=False)
    pipeline.dto = SimpleNamespace(is_public_channel=False, message_id="m")
    pipeline.tokens = []
    pipeline.callback = SimpleNamespace(
        in_progress=MagicMock(), done=MagicMock(), error=MagicMock()
    )
    pipeline.extract_qa = MagicMock()
    pipeline.upsert = MagicMock()

    result = pipeline()

    assert result is True
    pipeline.extract_qa.assert_not_called()
    pipeline.upsert.assert_not_called()
