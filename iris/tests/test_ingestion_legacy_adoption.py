"""Tests for adopting rows written by Iris versions without fingerprint stamps.

Older Iris versions stored the course language as a free-text name, wrote no
fingerprint stamps, and kept no record of which transcript a row came from. The
current skip and reuse checks must keep such rows when they provably match the
request, so an upgrade does not re-ingest every unit, and must rebuild them in
every other case.
"""

# pylint: disable=protected-access

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.pipeline.lecture_ingestion_pipeline import (
    LectureUnitPageIngestionPipeline,
    normalize_language,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
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
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
)

_UPDATE_MODULE = "iris.pipeline.lecture_ingestion_update_pipeline"
_UNIT_MODULE = "iris.pipeline.lecture_unit_pipeline"
_ROW_UUID = "55555555-5555-5555-5555-555555555555"
_FINGERPRINT = "v1:current"
_LEGACY_SEGMENT_UUID = "66666666-6666-6666-6666-666666666661"
_STAMPED_SEGMENT_UUID = "66666666-6666-6666-6666-666666666662"


# ── Language normalization ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        ("en", "en"),
        ("DE", "de"),
        ("zh-cn", "zh-cn"),
        ("English", "en"),
        (" english. ", "en"),
        ("Englisch", "en"),
        ("Deutsch", "de"),
        ("German", "de"),
        (None, None),
        ("", None),
        ("Unknown", None),
        ("Java", None),
        ("The text is written in English.", None),
    ],
)
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


def _attachment_needs_update(stored_language, requested_language="en") -> bool:
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            attachment_version=2, course_id=1, lecture_id=2, lecture_unit_id=3
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        )
    )
    # Legacy chunks: no run id, but a page version and a display number.
    rows = [
        SimpleNamespace(
            uuid=f"chunk-{page}",
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
                LectureUnitPageChunkSchema.PAGE_VERSION.value: 2,
                LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: None,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: page,
                LectureUnitPageChunkSchema.COURSE_LANGUAGE.value: stored_language,
            },
        )
        for page in (1, 2)
    ]
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows)),
            fetch_object_by_id=MagicMock(return_value=SimpleNamespace()),
        )
    )
    return pipeline.check_if_attachment_needs_update(2, requested_language)


def test_legacy_language_name_matches_its_iso_code():
    assert _attachment_needs_update("English") is False
    assert _attachment_needs_update("Deutsch", requested_language="de") is False


def test_legacy_language_name_of_another_language_is_rebuilt():
    assert _attachment_needs_update("German") is True


def test_garbage_legacy_language_is_rebuilt():
    assert _attachment_needs_update("Unknown") is True


# ── Legacy transcription rows ────────────────────────────────────────────


def _segment(slide, text, start, end):
    return SimpleNamespace(
        slide_number=slide, text=text, start_time=start, end_time=end
    )


_SEGMENTS = [
    _segment(1, "Hello and welcome.", 0.0, 4.5),
    _segment(1, "Today we look at sorting.", 4.5, 9.0),
    _segment(2, "Quicksort picks a pivot.", 9.0, 15.25),
]


def _legacy_row(page, text, start, end, fingerprint=None):
    return SimpleNamespace(
        uuid=f"{_ROW_UUID}-{page}-{start}",
        properties={
            LectureTranscriptionSchema.PAGE_NUMBER.value: page,
            LectureTranscriptionSchema.CONTENT_FINGERPRINT.value: fingerprint,
            LectureTranscriptionSchema.INGESTION_RUN_ID.value: None,
            LectureTranscriptionSchema.SEGMENT_TEXT.value: text,
            LectureTranscriptionSchema.SEGMENT_START_TIME.value: start,
            LectureTranscriptionSchema.SEGMENT_END_TIME.value: end,
        },
    )


def _matching_rows():
    # Old Iris joined the segments of one slide into one row.
    return [
        _legacy_row(1, "Hello and welcome. Today we look at sorting.", 0.0, 9.0),
        _legacy_row(2, "Quicksort picks a pivot.", 9.0, 15.25),
    ]


def _transcription_needs_update(rows, segments=None) -> bool:
    pipeline = object.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = None
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
                language="en", segments=segments or _SEGMENTS
            ),
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows)),
            fetch_object_by_id=MagicMock(return_value=SimpleNamespace()),
        )
    )
    return pipeline.check_if_transcription_needs_update()


def test_legacy_transcript_rows_matching_text_and_times_are_kept():
    assert _transcription_needs_update(_matching_rows()) is False


def test_legacy_transcript_rows_split_into_pieces_are_kept():
    # Long slide text was chunked into several rows that share the slide's times
    # and carry the chunk separator; neither changes the words.
    rows = [
        _legacy_row(1, "Hello and welcome.", 0.0, 9.0),
        _legacy_row(1, "Today we look at sorting.", 0.0, 9.0),
        _legacy_row(2, "Quicksort picks a pivot.", 9.0, 15.25),
    ]
    assert _transcription_needs_update(rows) is False


def test_legacy_transcript_rows_with_times_of_the_neighbouring_slide_are_kept():
    # Older versions took a split piece's times from the segment at its character
    # offset in the whole transcript, which at a slide border is the last segment of
    # the previous slide. The times are still segment boundaries of this transcript.
    rows = [
        _legacy_row(1, "Hello and welcome.", 0.0, 4.5),
        _legacy_row(1, "Today we look at sorting.", 4.5, 9.0),
        _legacy_row(2, "Quicksort picks a pivot.", 4.5, 15.25),
    ]
    assert _transcription_needs_update(rows) is False


def test_legacy_transcript_rows_with_a_time_outside_the_segments_are_rebuilt():
    rows = _matching_rows()
    rows[1] = _legacy_row(2, "Quicksort picks a pivot.", 9.0, 16.0)
    assert _transcription_needs_update(rows) is True


def test_legacy_transcript_rows_with_different_words_are_rebuilt():
    rows = _matching_rows()
    rows[1] = _legacy_row(2, "Mergesort splits the array.", 9.0, 15.25)
    assert _transcription_needs_update(rows) is True


def test_legacy_transcript_rows_with_shifted_times_are_rebuilt():
    # Same words, but a re-cut video: the times are not the transcript's own.
    rows = [
        _legacy_row(1, "Hello and welcome. Today we look at sorting.", 2.0, 11.0),
        _legacy_row(2, "Quicksort picks a pivot.", 11.0, 17.25),
    ]
    assert _transcription_needs_update(rows) is True


def test_legacy_transcript_rows_missing_the_last_segment_are_rebuilt():
    rows = [
        _legacy_row(1, "Hello and welcome.", 0.0, 4.5),
        _legacy_row(2, "Quicksort picks a pivot.", 9.0, 15.25),
    ]
    assert _transcription_needs_update(rows) is True


def test_legacy_transcript_rows_without_times_are_rebuilt():
    rows = _matching_rows()
    rows[0] = _legacy_row(1, "Hello and welcome. Today we look at sorting.", None, 9.0)
    assert _transcription_needs_update(rows) is True


def test_mixed_stamped_and_unstamped_transcript_rows_are_rebuilt():
    rows = _matching_rows()
    rows[1] = _legacy_row(
        2, "Quicksort picks a pivot.", 9.0, 15.25, fingerprint=_FINGERPRINT
    )
    assert _transcription_needs_update(rows) is True


# ── Legacy unit summary reuse ────────────────────────────────────────────


def _unit_dto() -> SimpleNamespace:
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
        ingestion_run_id="run-current",
        expected_chunk_counts_json=json.dumps({"1": 2}),
        pdf_page_count=1,
        pipeline_version=1,
        quality_score=0.9,
        quality_flags_json=None,
        content_unchanged=True,
        has_pdf=True,
    )


def _run_unit_pipeline_over_legacy_row(segment_fingerprints):
    pipeline = object.__new__(LectureUnitPipeline)
    pipeline.cancel_event = None
    pipeline.weaviate_client = MagicMock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    stored_row = SimpleNamespace(
        uuid=_ROW_UUID,
        properties={
            LectureUnitSchema.CONTENT_FINGERPRINT.value: None,
            LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: "legacy summary",
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
    segment_rows = [
        SimpleNamespace(
            uuid=f"segment-{index}",
            properties={LectureUnitSegmentSchema.CONTENT_FINGERPRINT.value: stamp},
        )
        for index, stamp in enumerate(segment_fingerprints)
    ]
    segment_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=segment_rows))
        )
    )

    with (
        patch(
            f"{_UNIT_MODULE}.init_lecture_unit_segment_schema",
            return_value=segment_collection,
        ),
        patch(
            f"{_UNIT_MODULE}.LectureUnitSegmentSummaryPipeline"
        ) as segment_pipeline_cls,
        patch(f"{_UNIT_MODULE}.LectureUnitSummaryPipeline") as summary_pipeline_cls,
    ):
        segment_pipeline_cls.return_value.return_value = ([], [])
        summary_pipeline_cls.return_value.return_value = ("fresh summary", [])
        pipeline(lecture_unit=_unit_dto(), initial_properties={})

    inserted = pipeline.lecture_unit_collection.data.insert.call_args.kwargs
    return summary_pipeline_cls, inserted


def test_legacy_unit_summary_is_reused_when_all_slide_summaries_are_legacy():
    summary_pipeline_cls, inserted = _run_unit_pipeline_over_legacy_row([None, None])

    summary_pipeline_cls.assert_not_called()
    properties = inserted["properties"]
    assert properties[LectureUnitSchema.LECTURE_UNIT_SUMMARY.value] == "legacy summary"
    # The reused row is stamped, so the next run takes the normal path.
    assert properties[LectureUnitSchema.CONTENT_FINGERPRINT.value] == _FINGERPRINT
    assert inserted["vector"] == [0.5, 0.6]


def test_legacy_unit_summary_is_rebuilt_when_a_slide_summary_was_regenerated():
    summary_pipeline_cls, inserted = _run_unit_pipeline_over_legacy_row(
        [None, _FINGERPRINT]
    )

    summary_pipeline_cls.assert_called_once()
    assert (
        inserted["properties"][LectureUnitSchema.LECTURE_UNIT_SUMMARY.value]
        == "fresh summary"
    )


# ── Purge of removed content ─────────────────────────────────────────────


def _update_pipeline() -> LectureIngestionUpdatePipeline:
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.cancel_event = None
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(course_id=1, lecture_id=2, lecture_unit_id=3),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    return pipeline


def _collection_with(rows) -> MagicMock:
    collection = MagicMock()
    collection.query.fetch_objects.return_value = SimpleNamespace(objects=rows)
    return collection


def _segment_row(uuid, fingerprint):
    return SimpleNamespace(
        uuid=uuid,
        properties={LectureUnitSegmentSchema.CONTENT_FINGERPRINT.value: fingerprint},
    )


def test_purge_deletes_only_unstamped_slide_summaries_first():
    source = _collection_with([SimpleNamespace(uuid="source-row")])
    segments = _collection_with(
        [
            _segment_row(_LEGACY_SEGMENT_UUID, None),
            _segment_row(_STAMPED_SEGMENT_UUID, _FINGERPRINT),
        ]
    )

    with (
        patch(
            f"{_UPDATE_MODULE}.init_lecture_unit_segment_schema",
            return_value=segments,
        ),
        patch(f"{_UPDATE_MODULE}.delete_many_with_retry") as delete,
    ):
        _update_pipeline()._invalidate_legacy_segments_before_purge(
            MagicMock(), source, MagicMock()
        )

    delete.assert_called_once()
    collection, id_filter, _ = delete.call_args.args
    assert collection is segments
    assert id_filter.value == [_LEGACY_SEGMENT_UUID]


def test_purge_keeps_slide_summaries_when_there_is_nothing_to_purge():
    segments = _collection_with([_segment_row(_LEGACY_SEGMENT_UUID, None)])

    with (
        patch(
            f"{_UPDATE_MODULE}.init_lecture_unit_segment_schema",
            return_value=segments,
        ),
        patch(f"{_UPDATE_MODULE}.delete_many_with_retry") as delete,
    ):
        _update_pipeline()._invalidate_legacy_segments_before_purge(
            MagicMock(), _collection_with([]), MagicMock()
        )

    delete.assert_not_called()
    segments.query.fetch_objects.assert_not_called()


def test_purge_reports_the_removed_row_count():
    transcription = _collection_with([])
    with (
        patch(
            f"{_UPDATE_MODULE}.init_lecture_transcription_schema",
            return_value=transcription,
        ),
        patch(
            f"{_UPDATE_MODULE}.delete_many_with_retry",
            return_value=SimpleNamespace(failed=0, matches=4, successful=4),
        ),
    ):
        assert _update_pipeline()._purge_stale_transcription(MagicMock()) == 4


@pytest.mark.parametrize("purged, expected_unchanged", [(0, True), (3, False)])
def test_stored_summaries_are_not_reused_after_a_purge_removed_rows(
    purged, expected_unchanged
):
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    # Neither a PDF nor a transcript: both purges run.
    pipeline.dto = IngestionPipelineExecutionDto.model_validate(
        {
            "pyrisLectureUnit": {
                "lectureUnitId": 3,
                "lectureId": 2,
                "courseId": 1,
                "lectureUnitName": "Unit",
                "lectureName": "Lecture",
                "courseName": "Course",
                "courseDescription": "",
                "courseLanguage": "en",
                "lectureUnitLink": "",
                "videoLink": "",
            },
            "lectureUnitId": 3,
            "settings": {
                "authenticationToken": "run-1",
                "artemisBaseUrl": "https://artemis.example",
            },
        }
    )
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline.cancel_event = None
    captured = {}

    def build_dto(*args):
        captured["content_unchanged"] = args[1]
        return SimpleNamespace()

    with (
        patch(f"{_UPDATE_MODULE}.VectorDatabase"),
        patch.object(
            LectureIngestionUpdatePipeline,
            "_purge_stale_page_chunks",
            return_value=purged,
        ),
        patch.object(
            LectureIngestionUpdatePipeline, "_purge_stale_transcription", return_value=0
        ),
        patch.object(
            LectureIngestionUpdatePipeline, "_send_heartbeats", return_value=None
        ),
        patch.object(
            LectureIngestionUpdatePipeline,
            "_build_lecture_unit_dto",
            side_effect=build_dto,
        ),
        patch(f"{_UPDATE_MODULE}.segments_are_complete", return_value=True),
        patch(f"{_UPDATE_MODULE}.LectureUnitPipeline") as unit_pipeline_cls,
        patch(f"{_UPDATE_MODULE}.IngestionAudit"),
    ):
        unit_pipeline_cls.return_value.return_value = []
        pipeline._run_ingestion(MagicMock(), {})

    assert captured["content_unchanged"] is expected_unchanged
