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

JAVA_LONG_MAX = 9223372036854775807


def _stored(
    version: int,
    source: str = "THREAD_RESOLVED",
    deleted: bool = False,
    conversation_id: str = "conv-1",
):
    """What fetch_object_by_id returns for an existing object."""
    return SimpleNamespace(
        properties={
            CourseMemorySchema.SOURCE.value: source,
            CourseMemorySchema.VERSION.value: version,
            CourseMemorySchema.DELETED.value: deleted,
            CourseMemorySchema.CONVERSATION_ID.value: conversation_id,
        }
    )


def _make_pipeline(
    existing=None,
    source: CourseMemorySource = CourseMemorySource.THREAD_RESOLVED,
    version: int = 1,
    post_id: str = "post-1",
    message_id: str = "answer-1",
    conversation_id: str = "conv-1",
):
    pipeline = object.__new__(CourseMemoryIngestionPipeline)
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.return_value = [0.1, 0.2]
    pipeline.collection = MagicMock()
    pipeline.collection.query.fetch_object_by_id.return_value = existing
    pipeline.dto = SimpleNamespace(
        course_id=7,
        post_id=post_id,
        message_id=message_id,
        conversation_id=conversation_id,
        source=source,
        version=version,
        verified_at=None,
        verified_by=None,
    )
    return pipeline


def _real_callback():
    """A real status callback that doesn't POST anywhere."""
    callback = CourseMemoryIngestionStatus(run_id="run", base_url="http://artemis")
    callback.on_status_update = MagicMock(return_value=True)
    return callback


def _written_properties(pipeline):
    """Properties of the single write the pipeline made, whichever call it used."""
    insert, replace = pipeline.collection.data.insert, pipeline.collection.data.replace
    assert insert.call_count + replace.call_count == 1
    call = insert.call_args if insert.called else replace.call_args
    return call.kwargs["properties"]


def _assert_nothing_written(pipeline):
    pipeline.collection.data.insert.assert_not_called()
    pipeline.collection.data.replace.assert_not_called()


# ---------------------------------------------------------------------------
# Keying
# ---------------------------------------------------------------------------


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
    first = _make_pipeline(existing=None, message_id="answer-1", version=1)
    second = _make_pipeline(existing=_stored(1), message_id="answer-2", version=2)

    first.upsert("q", "first part")
    second.upsert("q", "merged answer")

    assert first.collection.data.insert.call_args.kwargs["uuid"] == (
        second.collection.data.replace.call_args.kwargs["uuid"]
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_upsert_inserts_when_absent_and_embeds_only_question():
    pipeline = _make_pipeline(existing=None, version=3)

    pipeline.upsert("the question", "the answer")

    # Only the question is embedded.
    pipeline.llm_embedding.embed.assert_called_once_with("the question")
    pipeline.collection.data.insert.assert_called_once()
    pipeline.collection.data.replace.assert_not_called()

    props = _written_properties(pipeline)
    assert props[CourseMemorySchema.QUESTION.value] == "the question"
    assert props[CourseMemorySchema.ANSWER.value] == "the answer"
    assert props[CourseMemorySchema.COURSE_ID.value] == 7
    # The thread root is the dedup key; the answer id rides along as provenance.
    assert props[CourseMemorySchema.POST_ID.value] == "post-1"
    assert props[CourseMemorySchema.MESSAGE_ID.value] == "answer-1"
    # The write records the Artemis version it came from and is a live entry.
    assert props[CourseMemorySchema.VERSION.value] == 3
    assert props[CourseMemorySchema.DELETED.value] is False


def test_upsert_replaces_a_live_entry_with_a_newer_version():
    pipeline = _make_pipeline(
        existing=_stored(4, source="IRIS_AUTO"),
        source=CourseMemorySource.IRIS_CORRECTED,
        version=5,
    )

    pipeline.upsert("q", "corrected answer")

    pipeline.collection.data.replace.assert_called_once()
    pipeline.collection.data.insert.assert_not_called()
    assert _written_properties(pipeline)[CourseMemorySchema.VERSION.value] == 5


def test_stale_ingestion_is_dropped():
    """An older extraction finishing after a newer edit must not overwrite it.

    Two ingestions of the same thread run in independent background threads, so
    the one carrying the older Artemis state can finish last. It finds a higher
    version stored and gives up, so the entry keeps what the newer edit produced.
    """
    pipeline = _make_pipeline(existing=_stored(6), version=5)

    pipeline.upsert("q", "the older wording")

    _assert_nothing_written(pipeline)


def test_ingestion_with_the_same_version_as_stored_is_dropped():
    # Versions are minted once per operation, so an equal version can only be a
    # replayed request. Dropping it keeps the write idempotent.
    pipeline = _make_pipeline(existing=_stored(5), version=5)

    pipeline.upsert("q", "a")

    _assert_nothing_written(pipeline)


def test_stale_ingestion_cannot_resurrect_a_retracted_entry():
    """The resurrection race, closed durably.

    Ingestion accepted (version 5), then the resolving answer is un-marked and the
    retraction (version 6) completes first — leaving a tombstone. When the slow
    extraction finally writes, it finds the tombstone's newer version and drops
    the write instead of re-inserting the retracted answer. Unlike the in-process
    counter this replaced, the tombstone survives whichever webhook arrived first
    and whichever replica ran it.
    """
    pipeline = _make_pipeline(existing=_stored(6, deleted=True), version=5)

    pipeline.upsert("q", "the retracted answer")

    _assert_nothing_written(pipeline)


def test_newer_ingestion_overwrites_a_tombstone():
    # The thread was retracted (version 6) and then re-resolved (version 7): the
    # tombstone is replaced by a live entry in place.
    pipeline = _make_pipeline(existing=_stored(6, deleted=True), version=7)

    pipeline.upsert("q", "resolved again")

    pipeline.collection.data.replace.assert_called_once()
    props = _written_properties(pipeline)
    assert props[CourseMemorySchema.DELETED.value] is False
    assert props[CourseMemorySchema.VERSION.value] == 7


def test_entry_written_before_versioning_counts_as_version_zero():
    # Pre-versioning objects carry no version; anything Artemis sends is newer.
    legacy = SimpleNamespace(properties={CourseMemorySchema.SOURCE.value: "IRIS_AUTO"})
    pipeline = _make_pipeline(existing=legacy, version=1)

    pipeline.upsert("q", "a")

    pipeline.collection.data.replace.assert_called_once()


def test_latest_artemis_state_wins_regardless_of_trust_tier():
    """A newer THREAD_RESOLVED write replaces an older tutor-verified entry.

    Artemis decides which answer anchors the thread and what its provenance is,
    ranking tutor-endorsed anchors first. When it sends a community-resolved
    refresh with a higher version, that is because the tutor-verified answer is
    gone — deleted or un-marked — and refusing the write here would keep serving
    the retracted text as tutor-verified. Ordering is by version alone.
    """
    for verified in ("IRIS_AUTO", "TUTOR_WRITTEN", "IRIS_CORRECTED"):
        pipeline = _make_pipeline(
            existing=_stored(2, source=verified),
            source=CourseMemorySource.THREAD_RESOLVED,
            version=3,
        )

        pipeline.upsert("q", "the surviving community answer")

        pipeline.collection.data.replace.assert_called_once()
        props = _written_properties(pipeline)
        assert props[CourseMemorySchema.SOURCE.value] == "THREAD_RESOLVED"


def test_tutor_verification_replaces_a_community_entry():
    pipeline = _make_pipeline(
        existing=_stored(1, source="THREAD_RESOLVED"),
        source=CourseMemorySource.TUTOR_WRITTEN,
        version=2,
    )

    pipeline.upsert("q", "tutor answer")

    pipeline.collection.data.replace.assert_called_once()


def test_the_version_check_and_the_write_share_one_fetch():
    # One round-trip decides staleness; no separate exists() probe.
    pipeline = _make_pipeline(existing=_stored(1), version=2)

    pipeline.upsert("q", "a")

    pipeline.collection.query.fetch_object_by_id.assert_called_once_with(
        cm_module._deterministic_uuid("post-1", 7)
    )
    pipeline.collection.data.exists.assert_not_called()


# ---------------------------------------------------------------------------
# Retraction
# ---------------------------------------------------------------------------


def test_retraction_writes_a_versioned_tombstone_over_the_entry():
    """Un-resolving the last answer does not delete the object; it tombstones it."""
    pipeline = _make_pipeline(existing=_stored(3, source="TUTOR_WRITTEN"))

    assert pipeline.delete_for_thread("post-1", 7, version=4) is True

    pipeline.collection.data.delete_by_id.assert_not_called()
    pipeline.collection.data.replace.assert_called_once()
    call = pipeline.collection.data.replace.call_args.kwargs
    assert call["uuid"] == cm_module._deterministic_uuid("post-1", 7)
    props = call["properties"]
    assert props[CourseMemorySchema.DELETED.value] is True
    assert props[CourseMemorySchema.VERSION.value] == 4
    # Nothing of the retracted answer survives in the object.
    assert props[CourseMemorySchema.QUESTION.value] == ""
    assert props[CourseMemorySchema.ANSWER.value] == ""
    assert props[CourseMemorySchema.SOURCE.value] == ""
    # The purge keys stay so a later channel or course purge still removes it.
    assert props[CourseMemorySchema.COURSE_ID.value] == 7
    assert props[CourseMemorySchema.POST_ID.value] == "post-1"
    assert props[CourseMemorySchema.CONVERSATION_ID.value] == "conv-1"
    # A tombstone carries no vector: nothing about it should ever rank.
    assert "vector" not in call


def test_retraction_of_a_thread_without_an_entry_still_leaves_a_tombstone():
    """The retraction can overtake the very first ingestion of a thread.

    There is no object yet, so a plain delete would be a no-op and the ingestion
    landing afterwards would store the retracted answer. Inserting the tombstone
    gives that ingestion a newer version to trip over.
    """
    pipeline = _make_pipeline(existing=None)

    assert pipeline.delete_for_thread("post-1", 7, version=2) is True

    pipeline.collection.data.insert.assert_called_once()
    props = pipeline.collection.data.insert.call_args.kwargs["properties"]
    assert props[CourseMemorySchema.DELETED.value] is True
    assert props[CourseMemorySchema.VERSION.value] == 2
    assert props[CourseMemorySchema.CONVERSATION_ID.value] == ""


def test_stale_retraction_is_ignored():
    # The thread was retracted (v5) and re-resolved (v6) before this older
    # retraction (v5) arrived; the newer live entry must stand.
    pipeline = _make_pipeline(existing=_stored(6))

    assert pipeline.delete_for_thread("post-1", 7, version=5) is True

    _assert_nothing_written(pipeline)
    pipeline.collection.data.delete_by_id.assert_not_called()


def test_retraction_with_an_equal_version_still_applies():
    # Equal versions only happen when a thread deletion raced the last ingestion
    # for the version; the retraction has to win that tie or the entry outlives
    # its thread.
    pipeline = _make_pipeline(existing=_stored(5))

    assert pipeline.delete_for_thread("post-1", 7, version=5) is True

    pipeline.collection.data.replace.assert_called_once()


def test_thread_deletion_sends_a_final_version_nothing_can_follow():
    # Artemis sends Long.MAX_VALUE for a deleted thread; it must round-trip into
    # an int64 Weaviate property and beat every conceivable ingestion version.
    pipeline = _make_pipeline(existing=_stored(41))

    assert pipeline.delete_for_thread("post-1", 7, version=JAVA_LONG_MAX) is True

    props = pipeline.collection.data.replace.call_args.kwargs["properties"]
    assert props[CourseMemorySchema.VERSION.value] == JAVA_LONG_MAX

    late = _make_pipeline(existing=_stored(JAVA_LONG_MAX, deleted=True), version=42)
    late.upsert("q", "a")
    _assert_nothing_written(late)


def test_retraction_failure_is_reported_not_raised():
    pipeline = _make_pipeline(existing=_stored(1))
    pipeline.collection.data.replace.side_effect = RuntimeError("weaviate down")

    assert pipeline.delete_for_thread("post-1", 7, version=2) is False


# ---------------------------------------------------------------------------
# Channel and course purges (in-process counters, versionless scopes)
# ---------------------------------------------------------------------------


def test_channel_purge_during_ingestion_prevents_stale_write():
    """A channel purge mid-ingestion must not be undone by the older write.

    The purge cannot leave a tombstone per thread — it does not know the thread
    keys — so the channel-scoped counter is what stops the entry from coming back
    after its source channel was deleted or made private (req. 5).
    """
    pipeline = _make_pipeline(existing=None, conversation_id="conv-purged")
    start = cm_module._current_channel_delete_generation("conv-purged", 7)
    pipeline.delete_for_conversation("conv-purged", 7)

    pipeline.upsert("q", "a", start_channel_delete_gen=start)

    _assert_nothing_written(pipeline)


def test_channel_accepted_generation_survives_a_late_worker_start():
    """An ingestion accepted before a channel purge must not resurrect its entry.

    The webhook returns 202 and hands the run to a background thread, so the
    worker can start *after* a later-accepted purge already finished. Sampling
    the counter at accept time is what keeps the ordering tied to the requests.
    """
    pipeline = _make_pipeline(existing=None, conversation_id="conv-late")
    accepted_gen = CourseMemoryIngestionPipeline.channel_delete_generation_for(
        "conv-late", 7
    )
    pipeline.delete_for_conversation("conv-late", 7)
    pipeline.dto.is_public_channel = True
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock(return_value=("q", "a"))

    assert pipeline(start_channel_delete_gen=accepted_gen) is True

    _assert_nothing_written(pipeline)


def test_purge_of_another_channel_does_not_block_the_write():
    """The counter is per channel, so an unrelated purge must not skip this write."""
    pipeline = _make_pipeline(existing=None, conversation_id="conv-kept")
    start = cm_module._current_channel_delete_generation("conv-kept", 7)
    pipeline.delete_for_conversation("conv-other", 7)

    pipeline.upsert("q", "a", start_channel_delete_gen=start)

    pipeline.collection.data.insert.assert_called_once()


def test_generation_sampled_in_the_worker_still_writes_without_a_purge():
    """Omitting the accept-time samples falls back to sampling inside the run."""
    pipeline = _make_pipeline(existing=None, post_id="post-fresh")
    pipeline.dto.is_public_channel = True
    pipeline.tokens = []
    pipeline.callback = _real_callback()
    pipeline.extract_qa = MagicMock(return_value=("q", "a"))

    assert pipeline() is True

    pipeline.collection.data.insert.assert_called_once()
    assert pipeline.callback.status.run_state == RunStateEnum.FINISHED


def test_course_purge_during_ingestion_prevents_stale_write():
    """A course purge mid-ingestion must not be undone by the older write.

    The course scope is the one from which nothing can retract afterwards: once
    the course is gone Artemis has no post, channel or course left that could ask
    for the entry's removal, so a write landing after the purge is permanent.
    """
    pipeline = _make_pipeline(existing=None)
    pipeline.dto.course_id = 4242
    start = cm_module._current_course_delete_generation(4242)
    pipeline.delete_for_course(4242)

    pipeline.upsert("q", "a", start_course_delete_gen=start)

    _assert_nothing_written(pipeline)


def test_purge_of_another_course_does_not_block_the_write():
    pipeline = _make_pipeline(existing=None)
    start = cm_module._current_course_delete_generation(7)
    pipeline.delete_for_course(4243)

    pipeline.upsert("q", "a", start_course_delete_gen=start)

    pipeline.collection.data.insert.assert_called_once()


def test_course_purge_filters_on_the_course_alone():
    """Course deletion drops every conversation at once, so no channel id survives."""
    pipeline = _make_pipeline(existing=_stored(1))

    assert pipeline.delete_for_course(7) is True

    pipeline.collection.data.delete_many.assert_called_once()


def test_delete_generations_are_bounded():
    """The counters must not grow one entry per purged scope forever."""
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


# ---------------------------------------------------------------------------
# Skips
# ---------------------------------------------------------------------------


def test_non_public_channel_short_circuits_without_writing():
    pipeline = _make_pipeline(existing=None)
    pipeline.dto = SimpleNamespace(
        is_public_channel=False,
        post_id="post-1",
        message_id="answer-1",
        course_id=7,
        version=1,
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
    pipeline = _make_pipeline(existing=None)
    pipeline.dto = SimpleNamespace(
        is_public_channel=True,
        post_id="post-1",
        message_id="answer-1",
        course_id=7,
        version=1,
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
