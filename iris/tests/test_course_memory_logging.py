"""Logging assertions for course memory ingestion.

These exist so a run can be traced from webhook receipt to write. Without the
receipt line there is no way to tell "never triggered" apart from "triggered and
silently skipped", which is exactly the question that comes up when testing the
resolve/verify flows by hand.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.config import settings
from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryIngestionPipeline,
    _truncate,
)
from iris.web.routers import webhooks
from iris.web.status.course_memory_ingestion_status_callback import (
    CourseMemoryIngestionStatus,
)

# pylint: disable=protected-access


def _settings():
    return {
        "authenticationToken": "token",
        "artemisBaseUrl": "http://localhost:8080",
        "artemisLLMSelection": "CLOUD_AI",
        "variant": "default",
        "allowedModelIdentifier": "MODERATE",
    }


def _ingestion_dto(thread):
    return CourseMemoryIngestionExecutionDTO(
        settings=_settings(),
        courseId=42,
        conversationId="chan-9",
        postId="post-7",
        messageId="answer-9",
        version=3,
        source=CourseMemorySource.TUTOR_WRITTEN,
        isPublicChannel=True,
        thread=thread,
    )


def _message(message_id, *, verified=False, resolves=False):
    return {
        "id": message_id,
        "authorRole": "tutor",
        "content": f"content-{message_id}",
        "isVerifiedAnswer": verified,
        "resolvesPost": resolves,
    }


def test_ingestion_webhook_logs_receipt_before_dispatch(monkeypatch, caplog):
    dto = _ingestion_dto(
        [
            _message("post-7"),
            _message("answer-9", verified=True, resolves=True),
            _message("answer-11", resolves=True),
        ]
    )
    monkeypatch.setattr(webhooks, "validate_pipeline_variant", lambda *_: "default")
    started = MagicMock()
    monkeypatch.setattr(webhooks, "Thread", lambda **kw: started)

    with caplog.at_level(logging.INFO, logger="iris.web.routers.webhooks"):
        webhooks.course_memory_ingestion_webhook(dto)

    line = caplog.text
    assert "Course memory ingestion webhook received" in line
    assert (
        "course=42" in line and "thread=post-7" in line and "message=answer-9" in line
    )
    assert "source=TUTOR_WRITTEN" in line and "public=True" in line
    # The version is what orders this run against the thread's other operations, so a
    # dropped stale write can be matched back to the request that carried it.
    assert "version=3" in line
    # Flag counts make it obvious at a glance which messages the extractor will merge.
    assert "thread_size=3" in line
    assert "verified_flags=1" in line and "resolving_flags=2" in line


def test_deletion_webhook_logs_receipt(monkeypatch, caplog):
    dto = SimpleNamespace(
        course_id=42,
        post_id="post-7",
        version=5,
        conversation_id=None,
        whole_course=False,
        settings=None,
    )
    monkeypatch.setattr(webhooks, "validate_pipeline_variant", lambda *_: "default")
    monkeypatch.setattr(webhooks, "Thread", lambda **kw: MagicMock())

    with caplog.at_level(logging.INFO, logger="iris.web.routers.webhooks"):
        webhooks.course_memory_deletion_webhook(dto)

    assert "Course memory deletion webhook received" in caplog.text
    assert "course=42" in caplog.text and "thread=post-7" in caplog.text
    assert "version=5" in caplog.text


def test_deletion_webhook_logs_channel_scope(monkeypatch, caplog):
    # A channel-wide purge and a single-thread retraction have very different blast
    # radii, so the log line has to say which one was asked for.
    dto = SimpleNamespace(
        course_id=42,
        post_id=None,
        version=None,
        conversation_id="channel-3",
        whole_course=False,
        settings=None,
    )
    monkeypatch.setattr(webhooks, "validate_pipeline_variant", lambda *_: "default")
    monkeypatch.setattr(webhooks, "Thread", lambda **kw: MagicMock())

    with caplog.at_level(logging.INFO, logger="iris.web.routers.webhooks"):
        webhooks.course_memory_deletion_webhook(dto)

    assert "channel=channel-3" in caplog.text


def _skippable_pipeline(is_public_channel: bool):
    pipeline = object.__new__(CourseMemoryIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        is_public_channel=is_public_channel,
        post_id="post-7",
        message_id="answer-9",
        course_id=42,
    )
    pipeline.tokens = []
    callback = CourseMemoryIngestionStatus(run_id="run", base_url="http://artemis")
    callback.on_status_update = MagicMock(return_value=True)
    pipeline.callback = callback
    return pipeline


def test_non_public_skip_names_the_thread(caplog):
    pipeline = _skippable_pipeline(is_public_channel=False)

    with caplog.at_level(
        logging.INFO, logger="iris.pipeline.course_memory_ingestion_pipeline"
    ):
        assert pipeline() is True

    # A skip that named neither thread nor course could not be tied back to an action.
    assert "not a public channel" in caplog.text
    assert "thread post-7" in caplog.text and "course 42" in caplog.text


def test_disabled_feature_skip_names_the_thread(monkeypatch, caplog):
    monkeypatch.setattr(settings.course_memory, "enabled", False)
    pipeline = _skippable_pipeline(is_public_channel=True)

    with caplog.at_level(
        logging.INFO, logger="iris.pipeline.course_memory_ingestion_pipeline"
    ):
        assert pipeline() is True

    assert "Course memory is disabled" in caplog.text
    assert "thread post-7" in caplog.text and "course 42" in caplog.text


def test_upsert_logs_insert_replace_and_stale_branches(caplog):
    def _pipeline(existing, version=2):
        pipeline = object.__new__(CourseMemoryIngestionPipeline)
        pipeline.llm_embedding = MagicMock()
        pipeline.llm_embedding.embed.return_value = [0.1, 0.2]
        pipeline.collection = MagicMock()
        pipeline.collection.query.fetch_object_by_id.return_value = existing
        pipeline.dto = SimpleNamespace(
            course_id=42,
            post_id="post-7",
            message_id="answer-9",
            conversation_id="chan-9",
            source=CourseMemorySource.TUTOR_WRITTEN,
            version=version,
            verified_at=None,
            verified_by=None,
        )
        return pipeline

    def _stored(version, deleted=False):
        return SimpleNamespace(properties={"version": version, "deleted": deleted})

    logger_name = "iris.pipeline.course_memory_ingestion_pipeline"
    with caplog.at_level(logging.INFO, logger=logger_name):
        _pipeline(existing=None).upsert("q", "a")
    assert "Inserted course memory entry for thread post-7" in caplog.text
    assert "version 2" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=logger_name):
        _pipeline(existing=_stored(1)).upsert("q", "a")
    assert "Replaced course memory entry for thread post-7" in caplog.text
    assert "version 1 -> 2" in caplog.text

    # A dropped write has to say so, and say why: this is the only trace a stale
    # ingestion leaves, since Artemis still receives a plain FINISHED.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=logger_name):
        _pipeline(existing=_stored(3, deleted=True)).upsert("q", "a")
    assert "Ignoring stale course memory ingestion for thread post-7" in caplog.text
    assert "version 2 is not newer than the stored version 3 (tombstone)" in caplog.text


def test_truncate_collapses_whitespace_and_caps_length():
    assert _truncate("a\n\n  b") == "a b"
    long = "x" * 300
    assert len(_truncate(long)) == 161 and _truncate(long).endswith("…")
