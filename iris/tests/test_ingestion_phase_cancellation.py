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
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
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
