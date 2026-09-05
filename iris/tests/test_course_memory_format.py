import pytest
from pydantic import ValidationError

from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.domain.ingestion.deletion_pipeline_execution_dto import (
    CourseMemoryDeletionExecutionDto,
)
from iris.retrieval.course_memory_retrieval_utils import format_course_memories
from iris.vector_database.course_memory_schema import CourseMemorySchema


def _memory(source, message_id="m1", post_id="p1", course_id=3):
    return {
        CourseMemorySchema.QUESTION.value: "How do I submit?",
        CourseMemorySchema.ANSWER.value: "Use the submit button.",
        CourseMemorySchema.COURSE_ID.value: course_id,
        CourseMemorySchema.POST_ID.value: post_id,
        CourseMemorySchema.MESSAGE_ID.value: message_id,
        CourseMemorySchema.CONVERSATION_ID.value: "c1",
        CourseMemorySchema.SOURCE.value: source,
    }


def test_empty_returns_notice():
    assert format_course_memories([]) == "No relevant prior answers found."


def test_tutor_sources_are_labeled_verified():
    for source in ("TUTOR_WRITTEN", "IRIS_CORRECTED", "IRIS_AUTO"):
        out = format_course_memories([_memory(source)])
        assert "Verified prior answer" in out
        assert "not tutor-verified" not in out


def test_thread_resolved_is_labeled_unverified():
    out = format_course_memories([_memory("THREAD_RESOLVED")])
    assert "not tutor-verified" in out
    # Must not be misrepresented as a plain "Verified prior answer".
    assert not out.startswith("[Verified prior answer")


def test_backlink_is_a_followable_thread_link():
    out = format_course_memories([_memory("TUTOR_WRITTEN", post_id="7", course_id=3)])
    # The link must open the thread itself, so it carries the channel as conversationId and
    # the thread root as focusPostId — conversation_id holds the channel, not the thread.
    assert (
        "/courses/3/communication"
        "?conversationId=c1&focusPostId=7&openThreadOnFocus=1" in out
    )


def test_backlink_is_root_relative_not_absolute():
    # Regression: the link used to be built from settings.artemisBaseUrl, i.e. server.url.
    # That is the Spring Boot server's address, not the origin the student's browser is on
    # (dev serves the client on :9000 while server.url is :8080), so every citation opened
    # a page that never bootstrapped. The reply is only ever read inside the Artemis
    # client, so the path must stay relative to whatever origin that client is served from.
    out = format_course_memories([_memory("TUTOR_WRITTEN", post_id="7", course_id=3)])
    assert "http://" not in out
    assert "https://" not in out
    assert "source: /courses/3/communication" in out


def test_backlink_omits_raw_ids():
    # A bare id is ambiguous (posts and answers have independent id sequences) and means
    # nothing to a student, so it must not be offered as something to cite.
    out = format_course_memories(
        [_memory("TUTOR_WRITTEN", message_id="99", post_id="7")]
    )
    assert "source message" not in out
    assert "thread: 7" not in out


def test_entry_missing_backlink_fields_has_no_link():
    # Half a link is worse than none: an entry stored before backlinking is still usable,
    # just not citable.
    memory = _memory("TUTOR_WRITTEN")
    del memory[CourseMemorySchema.CONVERSATION_ID.value]
    out = format_course_memories([memory])
    assert "source:" not in out
    assert "/courses/" not in out
    assert "Use the submit button." in out


def _settings():
    return {
        "authenticationToken": "token",
        "artemisBaseUrl": "http://localhost:8080",
    }


def _message(message_id, *, verified=False, resolves=False):
    return {
        "id": message_id,
        "authorRole": "tutor",
        "content": f"content-{message_id}",
        "isVerifiedAnswer": verified,
        "resolvesPost": resolves,
    }


def _thread(*ids):
    """A minimal valid thread: a root post plus one verified answer."""
    return [_message(ids[0])] + [
        _message(message_id, verified=i == 0) for i, message_id in enumerate(ids[1:])
    ]


def test_ingestion_dto_fails_closed_on_public_channel():
    # An omitted isPublicChannel must default to False so private threads are not
    # ingested by a malformed/legacy payload.
    dto = CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        version=1,
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.THREAD_RESOLVED,
        settings=_settings(),
    )
    assert dto.is_public_channel is False


def _public_channel_dto(value):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        version=1,
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.THREAD_RESOLVED,
        isPublicChannel=value,
        settings=_settings(),
    )


def test_non_boolean_public_channel_is_rejected_not_coerced():
    # Pydantic's lax mode reads "yes"/"TRUE"/1 as True. Coercing a malformed
    # payload into permission to ingest would defeat the fail-closed default, so
    # the field is strict: a non-boolean is a rejected payload, not a private
    # thread in the store.
    for value in ("yes", "true", "TRUE", 1, 0, "false"):
        with pytest.raises(ValidationError):
            _public_channel_dto(value)


def test_boolean_public_channel_is_accepted():
    assert _public_channel_dto(True).is_public_channel is True
    assert _public_channel_dto(False).is_public_channel is False


def test_ingestion_requires_settings():
    # The worker reads settings.authentication_token before the pipeline (and its
    # callback) exist, so a null must fail at request validation rather than in a
    # background thread that can no longer report it.
    with pytest.raises(ValidationError):
        CourseMemoryIngestionExecutionDTO(
            courseId=1,
            conversationId="c1",
            postId="post-1",
            messageId="answer-1",
            version=1,
            thread=_thread("post-1", "answer-1"),
            source=CourseMemorySource.THREAD_RESOLVED,
            settings=None,
        )


def test_deletion_requires_settings():
    with pytest.raises(ValidationError):
        CourseMemoryDeletionExecutionDto(courseId=1, postId="post-1", settings=None)


def test_deletion_dto_accepts_settings():
    dto = CourseMemoryDeletionExecutionDto(
        courseId=1, postId="post-1", version=1, settings=_settings()
    )
    assert dto.post_id == "post-1"
    assert dto.settings.artemis_base_url == "http://localhost:8080"


def test_deletion_requires_exactly_one_scope():
    # Neither scope would delete nothing while reporting success; both would leave the
    # blast radius ambiguous. Reject at the boundary instead.
    with pytest.raises(ValidationError):
        CourseMemoryDeletionExecutionDto.model_validate(
            {"courseId": 1, "settings": _settings()}
        )
    with pytest.raises(ValidationError):
        CourseMemoryDeletionExecutionDto.model_validate(
            {
                "courseId": 1,
                "postId": "7",
                "version": 1,
                "conversationId": "c1",
                "settings": _settings(),
            }
        )


def test_deletion_accepts_channel_scope():
    dto = CourseMemoryDeletionExecutionDto.model_validate(
        {"courseId": 1, "conversationId": "c1", "settings": _settings()}
    )
    assert dto.conversation_id == "c1"
    assert dto.post_id is None


def _correction_dto(existing_answer):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        version=1,
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.IRIS_CORRECTED,
        existingAnswer=existing_answer,
        settings=_settings(),
    )


def test_correction_requires_existing_answer():
    # A correction is stored as tutor-verified; without the tutor's actual edit
    # the pipeline would persist LLM output under that label, so reject it.
    for blank in (None, "", "   "):
        with pytest.raises(ValidationError, match="IRIS_CORRECTED"):
            _correction_dto(blank)


def test_correction_accepts_non_blank_existing_answer():
    dto = _correction_dto("The tutor's corrected answer.")
    assert dto.existing_answer == "The tutor's corrected answer."


def _dto_with_source(source, existing_answer=None):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        version=1,
        thread=_thread("post-1", "answer-1"),
        source=source,
        existingAnswer=existing_answer,
        settings=_settings(),
    )


def test_approved_draft_requires_the_approved_text_verbatim():
    # IRIS_AUTO is a draft the tutor approved unchanged, and it is stored as
    # tutor-verified on the strength of that approval. Without the exact text the
    # extractor's paraphrase would be stored — and later served — as wording the
    # tutor signed off on, which they never saw. Same rule as for corrections.
    for blank in (None, "", "   "):
        with pytest.raises(ValidationError, match="IRIS_AUTO"):
            _dto_with_source(CourseMemorySource.IRIS_AUTO, blank)


def test_approved_draft_with_verbatim_text_is_accepted():
    dto = _dto_with_source(CourseMemorySource.IRIS_AUTO, "The approved draft.")
    assert dto.existing_answer == "The approved draft."


def test_sources_without_a_dashboard_signoff_need_no_verbatim_answer():
    # TUTOR_WRITTEN and THREAD_RESOLVED are extracted from the flagged thread
    # messages; there is no single approved wording to carry.
    for source in (
        CourseMemorySource.TUTOR_WRITTEN,
        CourseMemorySource.THREAD_RESOLVED,
    ):
        assert _dto_with_source(source).existing_answer is None


def _versioned_dto(**overrides):
    fields = dict(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId="answer-1",
        version=1,
        thread=_thread("post-1", "answer-1"),
        source=CourseMemorySource.THREAD_RESOLVED,
        settings=_settings(),
    )
    fields.update(overrides)
    return CourseMemoryIngestionExecutionDTO(**fields)


def test_ingestion_requires_a_version():
    # Without it the write cannot be ordered against a retraction or a newer edit
    # of the same thread; an unordered write is exactly the resurrection bug.
    payload = _versioned_dto().model_dump(by_alias=True)
    del payload["version"]
    with pytest.raises(ValidationError, match="version"):
        CourseMemoryIngestionExecutionDTO.model_validate(payload)


def test_ingestion_rejects_a_non_positive_version():
    # Artemis mints versions from 1 upwards; 0 or a negative number is a client bug,
    # and accepting it would make the write lose to every stored object.
    for bad in (0, -1):
        with pytest.raises(ValidationError, match="version"):
            _versioned_dto(version=bad)


def test_ingestion_accepts_a_java_long_max_version():
    # The largest value Artemis can ever send has to survive the wire and the
    # comparison against the stored int64.
    assert _versioned_dto(version=9223372036854775807).version == 9223372036854775807


def test_thread_deletion_requires_a_version():
    # A thread retraction becomes a versioned tombstone; without the version it
    # could not tell a stale ingestion from a newer re-resolution.
    with pytest.raises(ValidationError, match="version"):
        CourseMemoryDeletionExecutionDto.model_validate(
            {"courseId": 1, "postId": "post-1", "settings": _settings()}
        )


def test_thread_deletion_carries_its_version():
    dto = CourseMemoryDeletionExecutionDto.model_validate(
        {"courseId": 1, "postId": "post-1", "version": 9, "settings": _settings()}
    )
    assert dto.version == 9


def test_channel_and_course_deletions_need_no_version():
    # Both delete by filter across many threads; there is no per-thread version to
    # compare against, and Artemis sends none.
    channel = CourseMemoryDeletionExecutionDto.model_validate(
        {"courseId": 1, "conversationId": "c1", "settings": _settings()}
    )
    course = CourseMemoryDeletionExecutionDto.model_validate(
        {"courseId": 1, "wholeCourse": True, "settings": _settings()}
    )
    assert channel.version is None and course.version is None


def _thread_dto(thread, message_id="answer-1"):
    return CourseMemoryIngestionExecutionDTO(
        courseId=1,
        conversationId="c1",
        postId="post-1",
        messageId=message_id,
        version=1,
        thread=thread,
        source=CourseMemorySource.TUTOR_WRITTEN,
        settings=_settings(),
    )


def test_thread_must_flag_a_verified_answer():
    # Nothing flagged means nothing is tagged in the transcript, so the extractor
    # would pick a message of its own choosing and it would be stored as
    # tutor-verified.
    for thread in ([], [_message("post-1"), _message("answer-1")]):
        with pytest.raises(ValidationError, match="at least one message flagged"):
            _thread_dto(thread)


def test_thread_must_not_flag_several_verified_answers():
    # isVerifiedAnswer is derived from a single triggering answer in Artemis, so
    # duplicates mean an upstream bug and leave the anchor ambiguous.
    thread = [
        _message("post-1"),
        _message("answer-1", verified=True),
        _message("answer-2", verified=True),
    ]
    with pytest.raises(ValidationError, match="at most one"):
        _thread_dto(thread)


def test_thread_with_one_verified_answer_is_accepted():
    dto = _thread_dto(_thread("post-1", "answer-1", "answer-2"))
    assert [m.id for m in dto.thread] == ["post-1", "answer-1", "answer-2"]


def test_thread_with_several_resolving_answers_is_accepted():
    # A post is resolved if ANY of its answers resolves it, so several
    # resolvesPost flags are a legitimate state; they are merged into one answer.
    thread = [
        _message("post-1"),
        _message("answer-1", resolves=True),
        _message("answer-2", resolves=True),
        _message("answer-3", resolves=True),
    ]
    dto = _thread_dto(thread)
    assert sum(m.resolves_post for m in dto.thread) == 3


def test_resolving_answer_alone_anchors_the_thread():
    # Trigger B marks an answer resolving without any isVerifiedAnswer flag.
    thread = [_message("post-1"), _message("answer-1", resolves=True)]
    assert _thread_dto(thread).thread[1].resolves_post is True


def test_colliding_post_and_answer_ids_are_accepted():
    # Regression: Artemis draws post and answer ids from separate tables with
    # independent IDENTITY sequences, so a root post and one of its answers
    # routinely share a number. The anchor comes from the flags, never from an id
    # match, so the collision is irrelevant.
    # Same id on both, which is the case the namespace qualification exists to
    # survive: nothing may key off id equality.
    thread = [
        _message("7"),
        _message("7", verified=True),
    ]
    dto = _thread_dto(thread, message_id="7")
    assert sum(m.is_verified_answer for m in dto.thread) == 1
    assert dto.thread[1].id == "7"
