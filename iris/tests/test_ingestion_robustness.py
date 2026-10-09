"""Regression tests for ingestion robustness: deletion retries, the
transcription write path, and webhook worker failure reporting."""

# pylint: skip-file

import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.custom_exceptions import IngestionCancelledException  # noqa: E402
from iris.common.ingestion_errors import (  # noqa: E402
    TRANSCRIPT_INGESTION_FAILED,
    IngestionStageError,
)
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO  # noqa: E402
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (  # noqa: E402
    IngestionPipelineExecutionDto,
)
from iris.pipeline.delete_lecture_units_pipeline import (  # noqa: E402
    LectureUnitDeletionPipeline,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (  # noqa: E402
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.transcription_ingestion_pipeline import (  # noqa: E402
    TranscriptionIngestionPipeline,
)
from iris.tools.build_logs_analysis import (  # noqa: E402
    create_tool_get_build_logs_analysis,
)
from iris.vector_database.lecture_transcription_schema import (  # noqa: E402
    LectureTranscriptionSchema,
)
from iris.web.routers.webhooks import run_lecture_update_pipeline_worker  # noqa: E402


def _lecture_unit(lecture_unit_id: int = 1) -> LectureUnitPageDTO:
    return LectureUnitPageDTO(
        lectureUnitId=lecture_unit_id,
        lectureId=2,
        courseId=3,
    )


def test_deletion_pipeline_attempts_all_units_after_failures():
    pipeline = LectureUnitDeletionPipeline.__new__(LectureUnitDeletionPipeline)
    first = _lecture_unit(1)
    second = _lecture_unit(2)
    pipeline.lecture_units = [first, second]
    pipeline.delete_page_chunk = MagicMock(side_effect=[False, True])
    pipeline.delete_transcriptions = MagicMock(return_value=True)
    pipeline.delete_lecture_unit_segments = MagicMock(return_value=True)
    pipeline.delete_lecture_unit = MagicMock(return_value=True)

    assert pipeline.delete_entries_for_lecture_units() is False

    expected_calls = [call(first), call(second)]
    assert pipeline.delete_page_chunk.call_args_list == expected_calls
    assert pipeline.delete_transcriptions.call_args_list == expected_calls
    assert pipeline.delete_lecture_unit_segments.call_args_list == expected_calls
    assert pipeline.delete_lecture_unit.call_args_list == expected_calls


def test_transcription_embedding_does_not_hold_lock_while_updating_status():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = None
    lock = SimpleNamespace(inside=False)

    class TrackingLock:
        def __enter__(self):
            lock.inside = True

        def __exit__(self, *_args):
            lock.inside = False

    def update(**_kwargs):
        assert lock.inside is False

    def delete_inside_lock(**_kwargs):
        # The purge's delete runs inside the write lock.
        assert lock.inside is True
        return SimpleNamespace(failed=0, matches=0, successful=0)

    lecture_unit = SimpleNamespace(course_id=3, lecture_id=2, lecture_unit_id=1)
    batch = MagicMock()
    dynamic_context = MagicMock()
    dynamic_context.__enter__.return_value = batch
    dynamic_context.__exit__.return_value = None
    pipeline.collection = SimpleNamespace(
        batch=SimpleNamespace(
            dynamic=MagicMock(return_value=dynamic_context),
            failed_objects=[],
        ),
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(delete_many=MagicMock(side_effect=delete_inside_lock)),
    )
    pipeline.dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.callback = SimpleNamespace(update=MagicMock(side_effect=update))
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    chunk = {LectureTranscriptionSchema.SEGMENT_TEXT.value: "transcript"}

    with patch(
        "iris.pipeline.transcription_ingestion_pipeline.batch_update_lock",
        TrackingLock(),
    ):
        prepared_chunks = pipeline._prepare_batch_insert([chunk])
        pipeline._replace_prepared_chunks(lecture_unit, prepared_chunks)

    pipeline.callback.update.assert_called_once()
    # The purge deletes by unit identity inside the lock every run (no read); the
    # status update happens outside the lock, and the write carries a client uuid.
    pipeline.collection.query.fetch_objects.assert_not_called()
    pipeline.collection.data.delete_many.assert_called_once()
    add_call = batch.add_object.call_args
    assert add_call.kwargs["properties"] == chunk
    assert add_call.kwargs["vector"] == [0.1]
    assert "uuid" in add_call.kwargs


def test_transcription_ingestion_reraises_without_terminal_callback():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = None
    pipeline.callback = MagicMock()
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=3,
            lecture_id=2,
            lecture_unit_id=1,
            lecture_name="Lecture",
            lecture_unit_name="Unit",
            transcription=SimpleNamespace(language="en"),
            force_reingest=True,
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.tokens = []
    pipeline.chunk_transcription = MagicMock(
        side_effect=RuntimeError("chunking failed")
    )
    pipeline.collection = MagicMock()

    with pytest.raises(IngestionStageError, match="chunking failed") as exc_info:
        pipeline()

    assert exc_info.value.error_code == TRANSCRIPT_INGESTION_FAILED
    pipeline.callback.fail.assert_not_called()


def test_transcription_ingestion_clears_existing_rows_when_new_chunks_are_empty():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = None
    lecture_unit = SimpleNamespace(
        course_id=3,
        lecture_id=2,
        lecture_unit_id=1,
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        transcription=SimpleNamespace(language="en"),
        force_reingest=True,
    )
    pipeline.callback = MagicMock()
    pipeline.dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.tokens = []
    pipeline.chunk_transcription = MagicMock(return_value=[])
    pipeline.summarize_chunks = MagicMock(return_value=[])
    pipeline._prepare_batch_insert = MagicMock(return_value=[])
    pipeline.collection = MagicMock()
    pipeline.collection.data.delete_many.return_value = SimpleNamespace(
        failed=0, matches=0, successful=0
    )

    language, _tokens = pipeline()

    assert language == "en"
    # Nothing to write-then-sweep when the transcript is genuinely empty: the
    # commit phase falls back to clearing whatever is stored instead of leaving
    # a stale transcription behind forever (purge_other_rows refuses to purge
    # with no ids to keep, precisely to avoid wiping the unit on an accidental
    # empty write -- this is the deliberate, structurally-empty case instead).
    pipeline.collection.data.delete_many.assert_called_once()


def test_lecture_update_worker_reports_failure_without_lecture_unit_payload():
    dto = IngestionPipelineExecutionDto.model_validate(
        {
            "lectureUnitId": 77,
            "settings": {
                "authenticationToken": "run-1",
                "artemisBaseUrl": "https://artemis.example",
            },
        }
    )
    callback = MagicMock()

    with (
        patch(
            "iris.web.routers.webhooks.LectureIngestionUpdatePipeline",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "iris.web.routers.webhooks.IngestionStatusCallback",
            return_value=callback,
        ) as callback_cls,
        patch("iris.web.routers.webhooks.capture_exception") as capture_exception,
    ):
        run_lecture_update_pipeline_worker(dto, "default")

    callback_cls.assert_called_once_with(
        run_id="run-1",
        base_url="https://artemis.example",
        lecture_unit_id=77,
    )
    callback.fail.assert_called_once()
    capture_exception.assert_called_once()


def test_terminal_callback_is_skipped_when_run_is_no_longer_current():
    lecture_unit = SimpleNamespace(
        lecture_unit_id=7,
        course_id=1,
        course_name="Course",
        course_description="Desc",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        lecture_unit_link="https://artemis.example/unit/7",
        video_link=None,
        pdf_file_base64=None,
        transcription=None,
        display_page_numbers=[],
        attachment_version=1,
        chunk_counts_by_page=None,
        quality_flags=None,
        content_fingerprint=None,
        ingestion_run_id="run-x",
        quality_score=None,
    )
    dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(
            authentication_token="token",
            artemis_base_url="https://artemis.example",
            artemis_llm_selection="OPENAI",
        ),
    )
    pipeline = LectureIngestionUpdatePipeline(dto, cancel_event=threading.Event())
    callback = MagicMock()

    @contextmanager
    def cancelled_guard(*_args, **_kwargs):
        raise IngestionCancelledException(7, "Cancelled during terminal callback")
        yield

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"
        ) as database_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as lecture_unit_pipeline_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.ingestion_job_handler.current_job_guard",
            side_effect=cancelled_guard,
        ),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionAudit"
        ) as audit_cls,
    ):
        audit_cls.for_client.return_value.verify.return_value = None
        database_cls.return_value.get_client.return_value = MagicMock()
        lecture_unit_pipeline_cls.return_value.return_value = []

        with pytest.raises(
            IngestionCancelledException, match="Cancelled during terminal callback"
        ):
            pipeline._run_ingestion(callback, initial_properties={})

    callback.finish.assert_not_called()


def test_build_log_analysis_redacts_bare_tokens():
    submission = SimpleNamespace(
        build_failed=True,
        build_log_entries=[
            SimpleNamespace(
                message="request failed with token sk-review-token and ghp_reviewtoken"
            )
        ],
    )

    result = create_tool_get_build_logs_analysis(submission, MagicMock())()

    assert "sk-review-token" not in result
    assert "ghp_reviewtoken" not in result
    assert "[REDACTED_TOKEN]" in result
