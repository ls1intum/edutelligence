"""Cancellation checkpoints in the ingestion phase.

Embeddings, summaries and Weaviate writes have no subprocess to kill, so they
need explicit checkpoints — between units of work, and immediately before every
write, but never inside a delete/insert pair.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.common.custom_exceptions import IngestionCancelledException
from iris.pipeline.lecture_ingestion_pipeline import (
    LectureUnitPageIngestionPipeline,
)
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)

_MOD = "iris.pipeline.lecture_unit_pipeline"


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


def test_lecture_unit_replacement_is_not_torn_in_half():
    """Cancellation must not land between the delete and the insert."""
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.local = False
    pipeline.callback = MagicMock()
    pipeline.weaviate_client = MagicMock()
    pipeline.llm_embedding = MagicMock()
    collection = MagicMock()
    pipeline.lecture_unit_collection = collection

    # Cancel as late as possible: once the embedding is done, the very next
    # thing is the replacement.
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
        patch(f"{_MOD}.LectureUnitSegmentSummaryPipeline") as segment_cls,
        patch(f"{_MOD}.LectureUnitSummaryPipeline") as summary_cls,
    ):
        segment_cls.return_value.return_value = ([], [])
        summary_cls.return_value.return_value = ("summary", [])

        with pytest.raises(IngestionCancelledException):
            LectureUnitPipeline.__call__.__wrapped__(  # bypass @observe
                pipeline, lecture_unit, initial_properties={}
            )

    # Neither half of the replacement ran.
    collection.data.delete_many.assert_not_called()
    collection.data.insert.assert_not_called()


def test_page_chunking_stops_between_pages():
    """One Vision call per page — a superseded job must not chunk a whole deck.

    The unit already has no page chunks at this point (they were deleted just
    before), so giving up here costs nothing the successor does not already
    have to redo.
    """
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


def test_page_pipeline_propagates_cancellation_instead_of_reporting_failure():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = _cancelled()
    pipeline.callback = MagicMock()
    pipeline.dto = SimpleNamespace(lecture_unit=SimpleNamespace(lecture_unit_id=3))
    pipeline.tokens = []

    with pytest.raises(IngestionCancelledException):
        LectureUnitPageIngestionPipeline.__call__.__wrapped__(pipeline)

    pipeline.callback.fail.assert_not_called()


def test_page_replacement_does_not_cancel_after_delete():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            lecture_id=2,
            lecture_unit_id=3,
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.lecture_unit_collection = MagicMock()
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = []
    pipeline.collection = MagicMock()
    pipeline.collection.query.fetch_objects.return_value.objects = []
    batch = pipeline.collection.batch.rate_limit.return_value.__enter__.return_value

    def delete_then_cancel(*_args):
        pipeline.cancel_event.set()

    pipeline.delete_lecture_unit = MagicMock(side_effect=delete_then_cancel)
    prepared_chunks = [
        (
            {
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 1,
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "page",
            },
            [0.1],
        )
    ]

    pipeline.commit_prepared_replacement(prepared_chunks)

    pipeline.delete_lecture_unit.assert_called_once()
    batch.add_object.assert_called_once_with(
        properties=prepared_chunks[0][0], vector=prepared_chunks[0][1]
    )


def test_transcription_replacement_does_not_cancel_after_delete():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.dto = SimpleNamespace(lecture_unit=SimpleNamespace(lecture_unit_id=3))

    def delete_then_cancel(*_args):
        pipeline.cancel_event.set()

    pipeline.delete_existing_transcription_data = MagicMock(
        side_effect=delete_then_cancel
    )
    batch = MagicMock()
    dynamic_context = MagicMock()
    dynamic_context.__enter__.return_value = batch
    dynamic_context.__exit__.return_value = None
    pipeline.collection = SimpleNamespace(
        batch=SimpleNamespace(dynamic=MagicMock(return_value=dynamic_context))
    )
    prepared_chunks = [
        ({LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment"}, [0.2])
    ]

    pipeline.commit_prepared_replacement(prepared_chunks)

    pipeline.delete_existing_transcription_data.assert_called_once()
    batch.add_object.assert_called_once_with(
        properties=prepared_chunks[0][0], vector=prepared_chunks[0][1]
    )


def _segment_pipeline() -> LectureUnitSegmentSummaryPipeline:
    pipeline = LectureUnitSegmentSummaryPipeline.__new__(
        LectureUnitSegmentSummaryPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.callback = None
    pipeline.tokens = []
    pipeline.lecture_unit_dto = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        course_name="Course",
        lecture_name="Lecture",
    )
    pipeline.llm = MagicMock()
    pipeline.llm_embedding = MagicMock()
    pipeline.lecture_unit_segment_collection = MagicMock()
    pipeline.lecture_transcription_collection = MagicMock()
    pipeline.lecture_unit_page_chunk_collection = MagicMock()
    return pipeline


def test_segment_preparation_stops_after_embedding_if_cancelled():
    """Cancellation must still block the actual segment write.

    The last checkpoint has to be after the summary embedding is ready, because
    the write sits behind that extra work.
    """
    pipeline = _segment_pipeline()
    pipeline.pipeline = MagicMock(return_value="summary")

    slide = SimpleNamespace(
        properties={
            LectureUnitPageChunkSchema.PAGE_NUMBER.value: 5,
            LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 5,
            LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "page",
        }
    )
    pipeline.lecture_unit_page_chunk_collection.query.fetch_objects.return_value.objects = [
        slide
    ]
    pipeline.lecture_transcription_collection.query.fetch_objects.return_value.objects = (
        []
    )

    def embed_then_cancel(summary):
        del summary
        pipeline.cancel_event.set()
        return [0.1]

    pipeline.llm_embedding.embed.side_effect = embed_then_cancel

    with pytest.raises(IngestionCancelledException):
        pipeline.prepare_replacement()

    pipeline.lecture_unit_segment_collection.data.insert.assert_not_called()
    pipeline.lecture_unit_segment_collection.data.update.assert_not_called()


@pytest.mark.parametrize("existing_segment", [False, True])
def test_segment_commit_stops_before_writing_if_cancelled(existing_segment):
    """The commit window re-checks: a superseded job must not write prepared data."""
    pipeline = _segment_pipeline()
    pipeline.cancel_event.set()

    existing = [SimpleNamespace(uuid="segment-uuid")] if existing_segment else []
    pipeline.lecture_unit_segment_collection.query.fetch_objects.return_value.objects = (
        existing
    )

    with pytest.raises(IngestionCancelledException):
        pipeline.commit_prepared_replacement(
            [
                {
                    "slide_number": 5,
                    "display_page_number": 5,
                    "summary": "summary",
                    "embedding": [0.1],
                }
            ]
        )

    pipeline.lecture_unit_segment_collection.data.insert.assert_not_called()
    pipeline.lecture_unit_segment_collection.data.update.assert_not_called()
