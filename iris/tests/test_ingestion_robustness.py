"""Regression tests for ingestion robustness: deletion retries, the
transcription write path, and webhook worker failure reporting."""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
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


def test_transcription_batch_insert_does_not_hold_lock_while_updating_status():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    lock = SimpleNamespace(inside=False)

    class TrackingLock:
        def __enter__(self):
            lock.inside = True

        def __exit__(self, *_args):
            lock.inside = False

    def update(**_kwargs):
        assert lock.inside is False

    def sweep_fetch_inside_lock(**_kwargs):
        assert lock.inside is True
        return SimpleNamespace(objects=[])

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
            fetch_objects=MagicMock(side_effect=sweep_fetch_inside_lock)
        ),
        data=SimpleNamespace(delete_many=MagicMock()),
    )
    pipeline.callback = SimpleNamespace(update=MagicMock(side_effect=update))
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    pipeline.dto = SimpleNamespace(
        lecture_unit=_lecture_unit(),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    chunk = {LectureTranscriptionSchema.SEGMENT_TEXT.value: "transcript"}

    with patch(
        "iris.pipeline.transcription_ingestion_pipeline.batch_update_lock",
        TrackingLock(),
    ):
        pipeline.batch_insert([chunk])

    pipeline.callback.update.assert_called_once()
    # The generation sweep reads and (if needed) deletes inside the lock;
    # without stale rows nothing is deleted.
    pipeline.collection.query.fetch_objects.assert_called_once()
    pipeline.collection.data.delete_many.assert_not_called()
    batch.add_object.assert_called_once_with(properties=chunk, vector=[0.1])


def test_transcription_ingestion_reraises_without_terminal_callback():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.callback = MagicMock()
    pipeline.dto = SimpleNamespace(lecture_unit=_lecture_unit())
    pipeline.tokens = []
    pipeline.chunk_transcription = MagicMock(
        side_effect=RuntimeError("chunking failed")
    )

    with pytest.raises(IngestionStageError, match="chunking failed") as exc_info:
        pipeline()

    assert exc_info.value.error_code == TRANSCRIPT_INGESTION_FAILED
    pipeline.callback.fail.assert_not_called()


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
