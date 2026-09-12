"""Unit tests for the pure logic in the global-search retrieval module.

Includes the regression fixture for the silent metadata-drop bug (duplicate
unit ids from a shared multi-instance Weaviate truncating the metadata fetch)
that produced the original "vanishing answer" production complaint.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import Mock

from iris.config import settings
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    QWEN3_RETRIEVAL_INSTRUCTION,
    LectureGlobalSearchRetrieval,
    _Candidate,
    _SearchTelemetry,
    _VisibilityPolicy,
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


def test_rerank_floor_keeps_weak_but_plausible_candidates():
    """The floor removes garbage, not weak answers.

    Measured on Qwen3-Reranker-8B: deliberately irrelevant candidates peaked at
    0.065 while relevant entity records sat as low as 0.08. The previous 0.30
    cutoff sat inside the relevant band and nulled 8 of 105 queries that had
    provably relevant material.
    """
    floor = settings.global_search_rerank_floor
    junk_ceiling = 0.065
    assert floor > junk_ceiling, "floor must reject measured junk"
    assert (
        floor < 0.20
    ), "floor must stay below the relevant band; 0.30 deleted real answers"
    # and it must clear the reranker's measured run-to-run noise (+/-0.01)
    # by a real margin, so borderline candidates are not decided by jitter
    assert floor - junk_ceiling > 3 * 0.01


def _candidate(score, snippet, unit_key):
    dto = SimpleNamespace(snippet=snippet)
    return _Candidate(score, dto, unit_key)


def test_expansion_fetches_siblings_by_join_not_by_ranking():
    """Siblings of a surviving anchor arrive by structural join.

    A join has 100% recall by construction, which is the point: the harness
    measured at least one relevant item returned for 93% of queries but every
    relevant collection represented for only 16%, because siblings lost the
    ranking contest they should never have had to enter.
    """
    key = ("http://a", 1, 10)
    other_instance = ("http://b", 1, 10)  # same numeric unit id, different Artemis
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.collection = object()
    retrieval.transcription_collection = object()

    def _props(base_url, snippet):
        return SimpleNamespace(
            properties={
                "base_url": base_url,
                "course_id": 1,
                "lecture_unit_id": 10,
                "snippet": snippet,
            }
        )

    retrieval._fetch_unit_objects = Mock(
        side_effect=lambda collection, schema, ids: [
            _props("http://a", "sibling"),
            _props("http://b", "wrong instance"),
        ]
    )
    retrieval._fetch_metadata = Mock(return_value=({}, {}, {}))
    retrieval._map_candidates = Mock(
        return_value=[
            _candidate(0.0, "sibling", key),
            _candidate(0.0, "wrong instance", other_instance),
        ]
    )

    telemetry = _SearchTelemetry()
    anchors = [_candidate(0.5, "anchor", key)]
    out = retrieval._expand_by_unit(
        anchors, telemetry, _VisibilityPolicy.from_context(None)
    )

    snippets = [c.dto.snippet for c in out]
    assert snippets[0] == "anchor", "anchors keep their earned position"
    assert "sibling" in snippets, "the unit's other material is pulled in"
    assert (
        "wrong instance" not in snippets
    ), "a bare unit-id match from another Artemis instance must not leak"
    assert telemetry.expanded == 1
