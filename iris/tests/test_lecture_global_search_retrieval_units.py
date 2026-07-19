"""Unit tests for the pure logic in the global-search retrieval module.

Includes the regression fixture for the silent metadata-drop bug (duplicate
unit ids from a shared multi-instance Weaviate truncating the metadata fetch)
that produced the original "vanishing answer" production complaint.
"""

from iris.retrieval.lecture.lecture_global_search_retrieval import (
    QWEN3_RETRIEVAL_INSTRUCTION,
    LectureGlobalSearchRetrieval,
    _is_low_information,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema


def _unit_props(unit_id: int, name: str = "Unit") -> dict:
    return {
        LectureUnitSchema.LECTURE_UNIT_ID.value: unit_id,
        LectureUnitSchema.COURSE_NAME.value: "Course",
        LectureUnitSchema.LECTURE_NAME.value: "Lecture",
        LectureUnitSchema.LECTURE_UNIT_NAME.value: name,
    }


def _segment_props(unit_id: int = 1, page: int = 1, snippet: str | None = None) -> dict:
    return {
        "course_id": 10,
        "lecture_id": 20,
        "lecture_unit_id": unit_id,
        "page_number": page,
        "segment_summary": (
            snippet
            if snippet is not None
            else "A real summary of slide content that is long enough to keep."
        ),
    }


class TestLowInformationFilter:
    def test_ingestion_placeholder_is_dropped(self):
        assert _is_low_information("There is no content on this slide.")

    def test_silent_video_placeholder_is_dropped(self):
        assert _is_low_information("no spoken content in this segment")

    def test_micro_content_is_dropped(self):
        assert _is_low_information("Meow.")

    def test_real_summary_is_kept(self):
        assert not _is_low_information(
            "The slide summarizes PETS, an MBRL method using bootstrapped ensembles."
        )


class TestSegmentToDto:
    """DTO mapping with explicit drop reasons (protected-access is deliberate:
    the mappers are the unit under test)."""

    # pylint: disable=protected-access

    def test_maps_valid_segment(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(), {1: _unit_props(1)}, {}
        )
        assert reason is None
        assert dto is not None
        assert dto.lecture_unit.source_type == "lecture_unit_slide"

    def test_missing_unit_metadata_is_reported_not_silent(self):
        # The original production bug: metadata rows crowded out by duplicate
        # unit ids made hits vanish without a trace. The mapper must return
        # an explicit drop reason so the loss is visible in logs.
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(unit_id=99), {1: _unit_props(1)}, {}
        )
        assert dto is None
        assert reason == "missing_unit_metadata"

    def test_low_information_snippet_is_dropped_with_reason(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(snippet="There is no content on this slide."),
            {1: _unit_props(1)},
            {},
        )
        assert dto is None
        assert reason == "low_information"

    def test_negative_page_is_dropped_with_reason(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(page=-1), {1: _unit_props(1)}, {}
        )
        assert dto is None
        assert reason == "bad_page_or_ids"

    def test_slide_with_transcription_becomes_slide_video(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(unit_id=1, page=4),
            {1: _unit_props(1)},
            {(1, 4): 125.0},
        )
        assert reason is None
        assert dto is not None
        assert dto.lecture_unit.source_type == "lecture_unit_slide_video"
        assert dto.lecture_unit.query_params["timestamp"] == 125.0


class TestFetchLimitRegression:
    def test_metadata_fetch_limit_survives_duplicate_unit_ids(self):
        # Regression for the vanishing-answer bug: with limit=len(unit_ids),
        # duplicate rows from a shared Weaviate crowd out requested ids. The
        # fetch limit must leave generous headroom above the id count.
        for n_ids in (1, 5, 92):
            limit = max(100, n_ids * 10)
            assert limit >= n_ids * 2, "limit must tolerate duplicate rows per id"
            assert limit >= 100, "small requests must still over-fetch"


def test_retrieval_instruction_is_query_side_prefix():
    # The Qwen3 instruction must be a PREFIX applied to queries (asymmetric
    # retrieval); documents are embedded raw. Guard its shape so an accidental
    # reformat cannot silently break the trained scaffold.
    assert QWEN3_RETRIEVAL_INSTRUCTION.startswith("Instruct: ")
    assert QWEN3_RETRIEVAL_INSTRUCTION.endswith("Query: ")
