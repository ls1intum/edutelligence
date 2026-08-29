from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.config import settings
from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline import course_memory_ingestion_pipeline as cm_module
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
    post_id: str = "post-1",
    message_id: str = "answer-1",
    conversation_id: str = "conv-1",
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
        post_id=post_id,
        message_id=message_id,
        conversation_id=conversation_id,
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
    u1 = cm_module._deterministic_uuid("post-1", 7)
    u2 = cm_module._deterministic_uuid("post-1", 7)
    u3 = cm_module._deterministic_uuid("post-2", 7)
    assert u1 == u2
    assert u1 != u3


def test_uuid_is_keyed_on_the_thread_not_the_answer():
    """Two resolving answers in one thread must land on a single entry.

    Answer-keyed entries produced one near-identical Q/A pair per resolving
    answer, all competing for the same query in hybrid search.
    """
    first = _make_pipeline(exists=False, message_id="answer-1")
    second = _make_pipeline(exists=True, message_id="answer-2")

    first.upsert("q", "first part")
    second.upsert("q", "merged answer")

    assert first.collection.data.insert.call_args.kwargs["uuid"] == (
        second.collection.data.replace.call_args.kwargs["uuid"]
    )


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
    # The thread root is the dedup key; the answer id rides along as provenance.
    assert props[CourseMemorySchema.POST_ID.value] == "post-1"
    assert props[CourseMemorySchema.MESSAGE_ID.value] == "answer-1"


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


def test_delete_during_ingestion_prevents_stale_write():
    """A delete arriving mid-ingestion must not be undone by the older write."""
    pipeline = _make_pipeline(exists=False)
    obj_uuid = cm_module._deterministic_uuid("post-1", 7)
    # Ingestion snapshots the counter before its (slow) extraction...
    start = cm_module._current_delete_generation(obj_uuid)
    # ...a delete for the same key completes during that extraction...
    pipeline.delete_for_thread("post-1", 7)
    # ...so the now-stale write must be skipped.
    pipeline.upsert("q", "a", start_delete_gen=start)

    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


def test_ingestion_writes_when_no_delete_during_extraction():
    pipeline = _make_pipeline(exists=False)
    obj_uuid = cm_module._deterministic_uuid("post-1", 7)
    start = cm_module._current_delete_generation(obj_uuid)

    pipeline.upsert("q", "a", start_delete_gen=start)

    pipeline.collection.data.insert.assert_called_once()


def test_accepted_generation_survives_a_late_worker_start():
    """An ingestion accepted before a delete must not resurrect the entry.

    The webhook returns 202 and hands the run to a background thread, so the
    worker can start *after* a later-accepted delete already finished. Sampling
    the counter at accept time is what keeps the ordering tied to the requests.
    """
    pipeline = _make_pipeline(exists=False)
    # Accept time: the request is queued and the counter sampled here.
    accepted_gen = CourseMemoryIngestionPipeline.delete_generation_for("post-1", 7)
    # A deletion accepted afterwards runs to completion first.
    pipeline.delete_for_thread("post-1", 7)
    # Only now is the ingestion worker scheduled.
    pipeline.dto.is_public_channel = True
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock(return_value=("q", "a"))

    assert pipeline(start_delete_gen=accepted_gen) is True

    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


def test_generation_sampled_in_the_worker_still_writes_without_a_delete():
    """Omitting the accept-time sample falls back to sampling inside the run."""
    pipeline = _make_pipeline(exists=False, post_id="post-fresh")
    pipeline.dto.is_public_channel = True
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock(return_value=("q", "a"))

    assert pipeline() is True

    pipeline.collection.data.insert.assert_called_once()


def test_channel_purge_during_ingestion_prevents_stale_write():
    """A channel purge mid-ingestion must not be undone by the older write.

    The purge cannot bump the per-thread counter — it does not know the thread
    keys — so the channel-scoped counter is what stops the entry from coming back
    after its source channel was deleted or made private (req. 5).
    """
    pipeline = _make_pipeline(exists=False, conversation_id="conv-purged")
    start = cm_module._current_channel_delete_generation("conv-purged", 7)
    pipeline.delete_for_conversation("conv-purged", 7)

    pipeline.upsert("q", "a", start_channel_delete_gen=start)

    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


def test_channel_accepted_generation_survives_a_late_worker_start():
    """An ingestion accepted before a channel purge must not resurrect its entry.

    Same accept-time sampling as the per-thread case: the worker only starts after
    the later-accepted purge has already finished.
    """
    pipeline = _make_pipeline(exists=False, conversation_id="conv-late")
    accepted_gen = CourseMemoryIngestionPipeline.channel_delete_generation_for(
        "conv-late", 7
    )
    pipeline.delete_for_conversation("conv-late", 7)
    pipeline.dto.is_public_channel = True
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock(return_value=("q", "a"))

    assert pipeline(start_channel_delete_gen=accepted_gen) is True

    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


def test_purge_of_another_channel_does_not_block_the_write():
    """The counter is per channel, so an unrelated purge must not skip this write."""
    pipeline = _make_pipeline(exists=False, conversation_id="conv-kept")
    start = cm_module._current_channel_delete_generation("conv-kept", 7)
    pipeline.delete_for_conversation("conv-other", 7)

    pipeline.upsert("q", "a", start_channel_delete_gen=start)

    pipeline.collection.data.insert.assert_called_once()


def test_delete_targets_the_thread_entry():
    """Un-resolving or deleting the answer removes the thread's single entry."""
    pipeline = _make_pipeline(exists=True)

    assert pipeline.delete_for_thread("post-1", 7) is True

    pipeline.collection.data.delete_by_id.assert_called_once_with(
        cm_module._deterministic_uuid("post-1", 7)
    )


def test_non_public_channel_short_circuits_without_writing():
    pipeline = _make_pipeline(exists=False)
    pipeline.dto = SimpleNamespace(
        is_public_channel=False, post_id="post-1", message_id="answer-1", course_id=7
    )
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
    pipeline.dto = SimpleNamespace(
        is_public_channel=True, post_id="post-1", message_id="answer-1", course_id=7
    )
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock()
    pipeline.upsert = MagicMock()

    result = pipeline()

    assert result is True
    pipeline.extract_qa.assert_not_called()
    pipeline.upsert.assert_not_called()
    assert pipeline.callback.status.run_state == RunStateEnum.FINISHED


def test_course_purge_during_ingestion_prevents_stale_write():
    """A course purge mid-ingestion must not be undone by the older write.

    The course scope is the one from which nothing can retract afterwards: once
    the course is gone Artemis has no post, channel or course left that could ask
    for the entry's removal, so a write landing after the purge is permanent.
    """
    pipeline = _make_pipeline(exists=False)
    pipeline.dto.course_id = 4242
    start = cm_module._current_course_delete_generation(4242)
    pipeline.delete_for_course(4242)

    pipeline.upsert("q", "a", start_course_delete_gen=start)

    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


def test_purge_of_another_course_does_not_block_the_write():
    pipeline = _make_pipeline(exists=False)
    start = cm_module._current_course_delete_generation(7)
    pipeline.delete_for_course(4243)

    pipeline.upsert("q", "a", start_course_delete_gen=start)

    pipeline.collection.data.insert.assert_called_once()


def test_course_purge_filters_on_the_course_alone():
    """Course deletion drops every conversation at once, so no channel id survives."""
    pipeline = _make_pipeline(exists=True)

    assert pipeline.delete_for_course(7) is True

    pipeline.collection.data.delete_many.assert_called_once()


def test_delete_generations_are_bounded():
    """The counters must not grow one entry per deleted thread forever."""
    generations = cm_module._DeleteGenerations(max_entries=3)
    for key in ("a", "b", "c", "d"):
        generations.bump(key)

    assert len(generations._counters) == 3
    # The oldest key is evicted; a counter only has to outlive the ingestion that
    # sampled it, which is a matter of seconds.
    assert generations.get("a") == 0
    assert generations.get("d") == 1


def test_delete_generations_are_monotonic_per_key():
    generations = cm_module._DeleteGenerations()

    assert generations.bump("k") == 1
    assert generations.bump("k") == 2
    assert generations.get("k") == 2
