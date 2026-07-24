from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.config import settings
from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryIngestionPipeline,
)
from iris.vector_database.course_memory_schema import CourseMemorySchema
from iris.web.status.course_memory_ingestion_status_callback import (
    CourseMemoryIngestionStatus,
)

# pylint: disable=protected-access


def _make_pipeline(
    exists: bool,
    source: CourseMemorySource = CourseMemorySource.THREAD_RESOLVED,
    existing_source: str = None,
):
    pipeline = object.__new__(CourseMemoryIngestionPipeline)
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.return_value = [0.1, 0.2]
    pipeline.collection = MagicMock()
    pipeline.collection.data.exists.return_value = exists
    pipeline.collection.query.fetch_object_by_id.return_value = (
        SimpleNamespace(properties={CourseMemorySchema.SOURCE.value: existing_source})
        if existing_source
        else None
    )
    pipeline.dto = SimpleNamespace(
        course_id=7,
        message_id="msg-1",
        conversation_id="conv-1",
        source=source,
        verified_at=None,
        verified_by=None,
    )
    return pipeline


def _real_callback():
    """A real status callback (stages included) that doesn't POST anywhere."""
    callback = CourseMemoryIngestionStatus(run_id="run", base_url="http://artemis")
    callback.on_status_update = MagicMock(return_value=True)
    return callback


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
    pipeline = _make_pipeline(
        exists=True,
        source=CourseMemorySource.IRIS_CORRECTED,
        existing_source="IRIS_AUTO",
    )

    pipeline.upsert("q", "corrected answer")

    pipeline.collection.data.replace.assert_called_once()
    pipeline.collection.data.insert.assert_not_called()


def test_thread_resolved_never_downgrades_tutor_verified_entry():
    """Trigger B firing after Trigger A must not erase the trust tier or the
    tutor's exact wording (event ordering must not matter)."""
    for verified in ("IRIS_AUTO", "TUTOR_WRITTEN", "IRIS_CORRECTED"):
        pipeline = _make_pipeline(
            exists=True,
            source=CourseMemorySource.THREAD_RESOLVED,
            existing_source=verified,
        )

        pipeline.upsert("q", "re-extracted answer")

        pipeline.collection.data.replace.assert_not_called()
        pipeline.collection.data.insert.assert_not_called()


def test_thread_resolved_refreshes_thread_resolved_entry():
    pipeline = _make_pipeline(
        exists=True,
        source=CourseMemorySource.THREAD_RESOLVED,
        existing_source="THREAD_RESOLVED",
    )

    pipeline.upsert("q", "refreshed answer")

    pipeline.collection.data.replace.assert_called_once()


def test_tutor_verification_upgrades_thread_resolved_entry():
    pipeline = _make_pipeline(
        exists=True,
        source=CourseMemorySource.TUTOR_WRITTEN,
        existing_source="THREAD_RESOLVED",
    )

    pipeline.upsert("q", "tutor answer")

    pipeline.collection.data.replace.assert_called_once()
    # Tutor writes never need the provenance lookup.
    pipeline.collection.query.fetch_object_by_id.assert_not_called()


def test_non_public_channel_short_circuits_without_writing():
    pipeline = _make_pipeline(exists=False)
    pipeline.dto = SimpleNamespace(is_public_channel=False, message_id="m")
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock()
    pipeline.upsert = MagicMock()

    result = pipeline()

    assert result is True
    pipeline.extract_qa.assert_not_called()
    pipeline.upsert.assert_not_called()
    # The run must reach a terminal state, or the Artemis job never terminates.
    # A non-public-channel skip finishes successfully without writing.
    assert pipeline.callback.status.run_state == RunStateEnum.FINISHED


def test_disabled_feature_skips_ingestion_without_writing(monkeypatch):
    monkeypatch.setattr(settings.course_memory, "enabled", False)
    pipeline = _make_pipeline(exists=False)
    pipeline.dto = SimpleNamespace(is_public_channel=True, message_id="m")
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock()
    pipeline.upsert = MagicMock()

    result = pipeline()

    assert result is True
    pipeline.extract_qa.assert_not_called()
    pipeline.upsert.assert_not_called()
    assert pipeline.callback.status.run_state == RunStateEnum.FINISHED
