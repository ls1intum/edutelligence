"""Regression tests for PR 660 review feedback."""

# pylint: skip-file

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.custom_exceptions import IngestionCancelledException  # noqa: E402
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

    def update():
        assert lock.inside is False

    lecture_unit = SimpleNamespace(lecture_unit_id=1)
    batch = MagicMock()
    dynamic_context = MagicMock()
    dynamic_context.__enter__.return_value = batch
    dynamic_context.__exit__.return_value = None
    pipeline.collection = SimpleNamespace(
        batch=SimpleNamespace(dynamic=MagicMock(return_value=dynamic_context))
    )
    pipeline.dto = SimpleNamespace(lecture_unit=lecture_unit)
    pipeline.callback = SimpleNamespace(update=MagicMock(side_effect=update))
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    pipeline.delete_existing_transcription_data = MagicMock()
    chunk = {LectureTranscriptionSchema.SEGMENT_TEXT.value: "transcript"}

    with patch(
        "iris.pipeline.transcription_ingestion_pipeline.batch_update_lock",
        TrackingLock(),
    ):
        prepared_chunks = pipeline._prepare_batch_insert([chunk])
        pipeline._replace_prepared_chunks(lecture_unit, prepared_chunks)

    pipeline.callback.update.assert_called_once()
    batch.add_object.assert_called_once_with(properties=chunk, vector=[0.1])


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
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.tokens = []
    pipeline.chunk_transcription = MagicMock(return_value=[{"text": "segment"}])
    pipeline.summarize_chunks = MagicMock(return_value=[{"text": "segment"}])
    pipeline._prepare_batch_insert = MagicMock(
        return_value=[({"text": "segment"}, [0.1])]
    )
    pipeline.delete_existing_transcription_data = MagicMock(
        side_effect=RuntimeError("delete failed")
    )
    pipeline.collection = MagicMock()

    with pytest.raises(RuntimeError, match="delete failed"):
        pipeline()

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
    pipeline.delete_existing_transcription_data = MagicMock()
    pipeline._insert_prepared_chunks = MagicMock()

    language, _tokens = pipeline()

    assert language == "en"
    pipeline.delete_existing_transcription_data.assert_called_once_with(lecture_unit)
    pipeline._insert_prepared_chunks.assert_called_once_with([])


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

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"
        ) as database_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as lecture_unit_pipeline_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.ingestion_job_handler.is_current_job",
            return_value=False,
        ),
    ):
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
