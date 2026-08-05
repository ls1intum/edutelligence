"""Focused cancellation checkpoints for superseded ingestion runs."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.common.custom_exceptions import IngestionCancelledException
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


def _cancelled():
    event = threading.Event()
    event.set()
    return event


def test_transcription_summarization_loop_stops_when_cancelled():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = _cancelled()
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=7, lecture_name="L", lecture_unit_name="U"
        )
    )

    with pytest.raises(IngestionCancelledException):
        pipeline.summarize_chunks([{"segment_text": "a"}])


def test_page_chunking_stops_between_pages():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = _cancelled()
    pipeline.callback = MagicMock()
    pipeline.interpret_image = MagicMock()
    pipeline.get_course_language = MagicMock(return_value="en")

    doc = MagicMock()
    doc.page_count = 40
    doc.load_page.return_value.get_text.return_value = "text"

    with patch("iris.pipeline.lecture_ingestion_pipeline.fitz.open", return_value=doc):
        with pytest.raises(IngestionCancelledException):
            pipeline.chunk_data(
                lecture_pdf="/tmp/x.pdf",
                lecture_unit_slide_dto=SimpleNamespace(
                    lecture_unit_id=3, lecture_name="L", lecture_unit_name="U"
                ),
                base_url="https://artemis.example",
            )

    pipeline.interpret_image.assert_not_called()


def test_lecture_unit_replacement_is_skipped_after_cancellation():
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.local = False
    pipeline.callback = MagicMock()
    pipeline.weaviate_client = MagicMock()
    pipeline.llm_embedding = MagicMock()
    pipeline.lecture_unit_collection = MagicMock()

    def embed_then_cancel(summary):
        del summary
        pipeline.cancel_event.set()
        return [0.1]

    pipeline.llm_embedding.embed.side_effect = embed_then_cancel

    lecture_unit = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_unit_summary="summary",
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_cls,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as summary_cls,
    ):
        segment_cls.return_value.return_value = ([], [])
        summary_cls.return_value.return_value = ("summary", [])

        with pytest.raises(IngestionCancelledException):
            LectureUnitPipeline.__call__.__wrapped__(
                pipeline, lecture_unit, initial_properties={}
            )

    pipeline.lecture_unit_collection.data.delete_many.assert_not_called()
    pipeline.lecture_unit_collection.data.insert.assert_not_called()


def test_page_replacement_is_skipped_after_cancellation_during_embedding():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=3,
            course_id=1,
            lecture_id=2,
            lecture_unit_name="Unit",
            course_name="Course",
            pdf_file_base64="pdf",
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.check_if_attachment_needs_update = MagicMock(return_value=True)
    pipeline.chunk_data = MagicMock(
        return_value=[
            {
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 1,
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "page",
            }
        ]
    )
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = lambda _text: _cancel_then_vector(
        pipeline.cancel_event
    )
    pipeline.delete_lecture_unit = MagicMock()
    pipeline.collection = MagicMock()
    pipeline.collection.batch.rate_limit.return_value.__enter__.return_value = (
        MagicMock()
    )
    pipeline.get_course_language = MagicMock(return_value="en")

    with (
        patch(
            "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
            return_value="/tmp/x.pdf",
        ),
        patch("iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file"),
    ):
        with pytest.raises(IngestionCancelledException):
            LectureUnitPageIngestionPipeline.__call__.__wrapped__(pipeline)

    pipeline.delete_lecture_unit.assert_not_called()


def test_transcription_replacement_is_skipped_after_cancellation_during_embedding():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=3,
            lecture_name="Lecture",
            lecture_unit_name="Unit",
            transcription=SimpleNamespace(language="en"),
        )
    )
    pipeline.chunk_transcription = MagicMock(
        return_value=[
            {LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment", "page_number": 1}
        ]
    )
    pipeline.summarize_chunks = MagicMock(
        return_value=[
            {LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment", "page_number": 1}
        ]
    )
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = lambda _text: _cancel_then_vector(
        pipeline.cancel_event
    )
    pipeline.delete_existing_transcription_data = MagicMock()
    pipeline.collection = SimpleNamespace(
        batch=SimpleNamespace(dynamic=MagicMock(return_value=MagicMock()))
    )

    with pytest.raises(IngestionCancelledException):
        TranscriptionIngestionPipeline.__call__.__wrapped__(pipeline)

    pipeline.delete_existing_transcription_data.assert_not_called()


def _cancel_then_vector(cancel_event):
    cancel_event.set()
    return [0.1]
