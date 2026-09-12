"""Tests for the provably-safe skip and reuse paths of the ingestion pipelines.

These paths implement the LLM-economy rule: work is only skipped or reused when
fingerprint stamps prove the stored rows derive from the current content, and
any doubt falls through to a full recompute. Force-reingest bypasses the skips
so a quality re-run genuinely re-processes unchanged content, but keeps the
stored generation when the re-run scores worse.
"""

# pylint: disable=protected-access

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema

_ROW_UUID = "44444444-4444-4444-4444-444444444444"
_FINGERPRINT = "v1:current"
_RUN_ID = "run-current"


def _transcription_pipeline(rows) -> TranscriptionIngestionPipeline:
    pipeline = object.__new__(TranscriptionIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            lecture_id=2,
            lecture_unit_id=3,
            lecture_name="Lecture",
            lecture_unit_name="Unit",
            content_fingerprint=_FINGERPRINT,
            force_reingest=False,
            transcription=SimpleNamespace(
                language="en",
                segments=[
                    SimpleNamespace(slide_number=1),
                    SimpleNamespace(slide_number=2),
                ],
            ),
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows))
        )
    )
    return pipeline


def _transcript_row(page: int, fingerprint=_FINGERPRINT, run_id=_RUN_ID):
    return SimpleNamespace(
        properties={
            LectureTranscriptionSchema.PAGE_NUMBER.value: page,
            LectureTranscriptionSchema.CONTENT_FINGERPRINT.value: fingerprint,
            LectureTranscriptionSchema.INGESTION_RUN_ID.value: run_id,
        }
    )


def test_transcription_skip_requires_current_stamps_and_exact_slide_set():
    pipeline = _transcription_pipeline([_transcript_row(1), _transcript_row(2)])
    assert pipeline.check_if_transcription_needs_update() is False


def test_transcription_needs_update_without_rows():
    assert _transcription_pipeline([]).check_if_transcription_needs_update() is True


def test_transcription_needs_update_on_foreign_or_missing_stamp():
    foreign = [_transcript_row(1, fingerprint="v1:other"), _transcript_row(2)]
    assert (
        _transcription_pipeline(foreign).check_if_transcription_needs_update() is True
    )

    unstamped = [_transcript_row(1, fingerprint=None), _transcript_row(2)]
    assert (
        _transcription_pipeline(unstamped).check_if_transcription_needs_update() is True
    )


def test_transcription_needs_update_on_slide_set_mismatch():
    partial = [_transcript_row(1)]
    assert (
        _transcription_pipeline(partial).check_if_transcription_needs_update() is True
    )


def test_transcription_needs_update_on_mixed_generations():
    mixed = [_transcript_row(1), _transcript_row(2, run_id="run-old")]
    assert _transcription_pipeline(mixed).check_if_transcription_needs_update() is True


def test_transcription_needs_update_without_request_fingerprint():
    pipeline = _transcription_pipeline([_transcript_row(1), _transcript_row(2)])
    pipeline.dto.lecture_unit.content_fingerprint = None
    assert pipeline.check_if_transcription_needs_update() is True


def _unit_lecture_dto(content_unchanged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        course_id=1,
        course_name="Course",
        course_description="",
        course_language="en",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        lecture_unit_link="",
        video_link="",
        base_url="https://artemis.example",
        lecture_unit_summary="",
        content_fingerprint=_FINGERPRINT,
        ingestion_run_id=_RUN_ID,
        expected_chunk_counts_json=json.dumps({"1": 2}),
        pdf_page_count=1,
        pipeline_version=1,
        quality_score=0.9,
        quality_flags_json=None,
        content_unchanged=content_unchanged,
    )


def test_unit_pipeline_reuses_stored_summary_when_content_is_unchanged():
    pipeline = object.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = MagicMock()
    pipeline.local = False
    pipeline.callback = None
    embed = MagicMock()
    pipeline.llm_embedding = SimpleNamespace(embed=embed)
    stored_row = SimpleNamespace(
        uuid=_ROW_UUID,
        properties={
            LectureUnitSchema.CONTENT_FINGERPRINT.value: _FINGERPRINT,
            LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: "stored summary",
        },
        vector={"default": [0.5, 0.6]},
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[stored_row]))
        ),
        data=SimpleNamespace(
            insert=MagicMock(return_value=_ROW_UUID),
            delete_many=MagicMock(
                return_value=SimpleNamespace(failed=0, matches=0, successful=0)
            ),
        ),
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_pipeline_cls,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as summary_pipeline_cls,
    ):
        tokens = pipeline(
            lecture_unit=_unit_lecture_dto(content_unchanged=True),
            initial_properties={},
        )

    # Zero LLM calls: no segment summaries, no unit summary, no embedding.
    segment_pipeline_cls.assert_not_called()
    summary_pipeline_cls.assert_not_called()
    embed.assert_not_called()
    assert tokens == []
    inserted = pipeline.lecture_unit_collection.data.insert.call_args.kwargs
    assert (
        inserted["properties"][LectureUnitSchema.LECTURE_UNIT_SUMMARY.value]
        == "stored summary"
    )
    assert inserted["vector"] == [0.5, 0.6]


def test_unit_pipeline_recomputes_when_stored_stamp_differs():
    pipeline = object.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = MagicMock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    stored_row = SimpleNamespace(
        uuid=_ROW_UUID,
        properties={
            LectureUnitSchema.CONTENT_FINGERPRINT.value: "v1:previous",
            LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: "stored summary",
        },
        vector={"default": [0.5]},
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[stored_row]))
        ),
        data=SimpleNamespace(
            insert=MagicMock(return_value=_ROW_UUID),
            delete_many=MagicMock(
                return_value=SimpleNamespace(failed=0, matches=0, successful=0)
            ),
        ),
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_pipeline_cls,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as summary_pipeline_cls,
    ):
        segment_pipeline_cls.return_value.return_value = ([], [])
        summary_pipeline_cls.return_value.return_value = ("fresh summary", [])
        pipeline(
            lecture_unit=_unit_lecture_dto(content_unchanged=True),
            initial_properties={},
        )

    # The stamp does not match the current content: reuse must not happen.
    segment_pipeline_cls.assert_called_once()
    summary_pipeline_cls.assert_called_once()


def test_unit_pipeline_stamps_the_ingestion_ledger():
    pipeline = object.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = MagicMock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(
            insert=MagicMock(return_value=_ROW_UUID),
            delete_many=MagicMock(
                return_value=SimpleNamespace(failed=0, matches=0, successful=0)
            ),
        ),
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_pipeline_cls,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as summary_pipeline_cls,
    ):
        segment_pipeline_cls.return_value.return_value = ([], [])
        summary_pipeline_cls.return_value.return_value = ("summary", [])
        pipeline(
            lecture_unit=_unit_lecture_dto(content_unchanged=False),
            initial_properties={},
        )

    stored = pipeline.lecture_unit_collection.data.insert.call_args.kwargs["properties"]
    assert stored[LectureUnitSchema.INGESTION_RUN_ID.value] == _RUN_ID
    assert stored[LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value] == json.dumps({"1": 2})
    assert stored[LectureUnitSchema.PIPELINE_VERSION.value] == 1
    assert stored[LectureUnitSchema.QUALITY_SCORE.value] == 0.9
