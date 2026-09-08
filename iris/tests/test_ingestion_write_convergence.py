"""Regression tests for the convergent lecture ingestion write path.

Covers the invariants that keep a lecture unit from ending up partially
ingested: all LLM work happens before any delete, every Weaviate batch and
delete result is verified, vision failures fail the run instead of degrading
it, and stale segments are pruned.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.ingestion_errors import (
    SLIDE_VISION_FAILED,
    STALE_CONTENT_DELETE_FAILED,
    VECTOR_STORE_WRITE_FAILED,
    IngestionStageError,
)
from iris.pipeline.lecture_ingestion_pipeline import (
    VISION_MAX_ATTEMPTS,
    LectureUnitPageIngestionPipeline,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


def _delete_result(failed: int = 0, matches: int = 0) -> SimpleNamespace:
    return SimpleNamespace(failed=failed, matches=matches, successful=matches - failed)


def _patch_pdf(monkeypatch, page_count: int = 1) -> None:
    fake_doc = SimpleNamespace(page_count=page_count)
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
        MagicMock(return_value="/tmp/test.pdf"),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file",
        MagicMock(),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.fitz.open",
        MagicMock(return_value=fake_doc),
    )


def _page_pipeline(events: list) -> LectureUnitPageIngestionPipeline:
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    lecture_unit = SimpleNamespace(
        pdf_file_base64="cGRm",
        attachment_version=2,
        course_id=11,
        lecture_id=12,
        lecture_unit_id=13,
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        course_name="Course",
        display_page_numbers=None,
    )
    pipeline.dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.callback = SimpleNamespace(update=MagicMock(), fail=MagicMock())
    pipeline.tokens = []
    pipeline.course_language = "en"
    pipeline._hidden_until_by_page = {}

    def record_delete(**_kwargs):
        events.append("delete")
        return _delete_result(matches=1)

    batch = SimpleNamespace(
        add_object=MagicMock(side_effect=lambda **_kwargs: events.append("insert"))
    )
    batch_context = MagicMock()
    batch_context.__enter__ = MagicMock(return_value=batch)
    batch_context.__exit__ = MagicMock(return_value=None)
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(delete_many=MagicMock(side_effect=record_delete)),
        batch=SimpleNamespace(
            rate_limit=MagicMock(return_value=batch_context),
            failed_objects=[],
        ),
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        )
    )
    pipeline.llm_embedding = SimpleNamespace(
        embed=MagicMock(side_effect=lambda _text: events.append("embed") or [0.1])
    )
    return pipeline


def test_page_replacement_deletes_only_after_all_llm_work(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    chunk = {LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "text"}
    pipeline.chunk_data = MagicMock(
        side_effect=lambda **_kwargs: events.append("chunk") or [chunk]
    )
    _patch_pdf(monkeypatch)

    course_language = pipeline()[0]

    assert course_language == "en"
    assert events == ["chunk", "embed", "delete", "insert"]
    pipeline.callback.fail.assert_not_called()


def test_page_replacement_fails_run_when_batch_drops_objects(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.collection.batch.failed_objects = [SimpleNamespace(message="boom")]
    chunk = {LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "text"}
    pipeline.chunk_data = MagicMock(return_value=[chunk])
    _patch_pdf(monkeypatch)

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline()

    assert exc_info.value.error_code == VECTOR_STORE_WRITE_FAILED
    pipeline.callback.fail.assert_not_called()


def test_page_replacement_fails_run_when_delete_fails(monkeypatch):
    events: list = []
    pipeline = _page_pipeline(events)
    pipeline.collection.data.delete_many = MagicMock(
        return_value=_delete_result(failed=1, matches=3)
    )
    chunk = {LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "text"}
    pipeline.chunk_data = MagicMock(return_value=[chunk])
    _patch_pdf(monkeypatch)

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline()

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED


def test_attachment_needs_update_is_structural():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            attachment_version=2, course_id=1, lecture_id=2, lecture_unit_id=3
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )

    def needs_update(stored_chunks, page_count):
        rows = [
            SimpleNamespace(
                properties={
                    LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
                    LectureUnitPageChunkSchema.PAGE_VERSION.value: version,
                }
            )
            for page, version in stored_chunks
        ]
        pipeline.collection = SimpleNamespace(
            query=SimpleNamespace(
                fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows))
            )
        )
        return pipeline.check_if_attachment_needs_update(page_count)

    assert needs_update([], page_count=2) is True
    assert needs_update([(1, None), (2, None)], page_count=2) is True
    assert needs_update([(1, 3), (2, 3)], page_count=2) is True
    assert needs_update([(1, 2)], page_count=2) is True
    assert needs_update([(1, 2), (2, 2), (3, 2)], page_count=2) is True
    assert needs_update([(1, 2), (2, 2)], page_count=2) is False


def test_interpret_image_retries_then_fails_the_run():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.tokens = []
    pipeline._append_tokens = MagicMock()
    pipeline.llm_chat = SimpleNamespace(
        chat=MagicMock(side_effect=RuntimeError("vision down"))
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline.interpret_image("aW1n", "", "Lecture", "en")

    assert exc_info.value.error_code == SLIDE_VISION_FAILED
    assert pipeline.llm_chat.chat.call_count == VISION_MAX_ATTEMPTS


def test_interpret_image_rejects_empty_descriptions():
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.tokens = []
    pipeline._append_tokens = MagicMock()
    empty_response = SimpleNamespace(
        token_usage=None,
        contents=[
            SimpleNamespace(
                text_content='{"display_page_number": 3, "academic_description": ""}'
            )
        ],
    )
    pipeline.llm_chat = SimpleNamespace(chat=MagicMock(return_value=empty_response))

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline.interpret_image("aW1n", "", "Lecture", "en")

    assert exc_info.value.error_code == SLIDE_VISION_FAILED
    assert pipeline.llm_chat.chat.call_count == VISION_MAX_ATTEMPTS


def test_update_pipeline_forwards_stage_error_code_once():
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            course_name="Course",
            course_description="",
            lecture_id=2,
            lecture_name="Lecture",
            lecture_unit_id=3,
            lecture_unit_name="Unit",
            lecture_unit_link="",
            video_link=None,
            transcription=None,
            content_fingerprint=None,
        ),
        settings=SimpleNamespace(
            authentication_token="run-1",
            artemis_base_url="https://artemis.example",
            artemis_llm_selection=None,
        ),
    )
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline._run_ingestion = MagicMock(
        side_effect=IngestionStageError(SLIDE_VISION_FAILED, "page 4 failed")
    )
    callback = MagicMock()

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionStatusCallback",
            return_value=callback,
        ),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as unit_pipeline,
    ):
        unit_pipeline.fetch_existing_properties.return_value = {}
        pipeline._run()

    callback.fail.assert_called_once()
    assert callback.fail.call_args.kwargs["code"] == SLIDE_VISION_FAILED


def test_stale_segments_are_pruned_after_the_slide_loop():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_name="Lecture",
    )
    delete_many = MagicMock(return_value=_delete_result(matches=2))
    pipeline.lecture_unit_segment_collection = SimpleNamespace(
        data=SimpleNamespace(delete_many=delete_many)
    )

    pipeline._prune_stale_segments(1, 5)

    delete_many.assert_called_once()


def test_stale_segment_prune_failure_fails_the_run():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_name="Lecture",
    )
    pipeline.lecture_unit_segment_collection = SimpleNamespace(
        data=SimpleNamespace(
            delete_many=MagicMock(return_value=_delete_result(failed=1, matches=2))
        )
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline._prune_stale_segments(1, 5)

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED
