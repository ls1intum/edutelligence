"""Unit tests for the pure logic in the global-search retrieval module.

Includes the regression fixture for the silent metadata-drop bug (duplicate
unit ids from a shared multi-instance Weaviate truncating the metadata fetch)
that produced the original "vanishing answer" production complaint.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import Mock, patch

from weaviate.classes.query import Filter

from iris.config import settings
from iris.domain.search.global_search_dto import AccessContext, EntitySourceDTO
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    QWEN3_RETRIEVAL_INSTRUCTION,
    LectureGlobalSearchRetrieval,
    _Candidate,
    _course_scope_filter,
    _is_low_information,
    _SearchTelemetry,
    _VisibilityPolicy,
)
from iris.vector_database.lecture_transcription_schema import LectureTranscriptionSchema
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

    def test_single_word_slide_is_dropped(self):
        assert _is_low_information("The slide contains a single word: 'Loading'.")

    def test_real_summary_is_kept(self):
        assert not _is_low_information(
            "The slide summarizes PETS, an MBRL method using bootstrapped ensembles."
        )

    def test_short_but_complete_summary_is_kept(self):
        # A concise, correct summary is valid content, not junk; a character-count
        # floor previously dropped it purely for being short.
        assert not _is_low_information("A stack is LIFO.")


class TestSegmentToDto:
    """DTO mapping with explicit drop reasons (protected-access is deliberate:
    the mappers are the unit under test)."""

    # pylint: disable=protected-access

    def test_maps_valid_segment(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(), {(None, 1): _unit_props(1)}, {}
        )
        assert reason is None
        assert dto is not None
        assert dto.lecture_unit.source_type == "lecture_unit_slide"

    def test_missing_unit_metadata_is_reported_not_silent(self):
        # The original production bug: metadata rows crowded out by duplicate
        # unit ids made hits vanish without a trace. The mapper must return
        # an explicit drop reason so the loss is visible in logs.
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(unit_id=99), {(None, 1): _unit_props(1)}, {}
        )
        assert dto is None
        assert reason == "missing_unit_metadata"

    def test_low_information_snippet_is_dropped_with_reason(self):
        # Regression: this must fire regardless of reranking, since
        # _rerank_and_gate's floor is skipped whenever rerank_result is None
        # (no reranker configured, timeout/API failure, or the results-list
        # path with reranking turned off) — this mapper-level check is the
        # only thing standing between an ingestion placeholder and the UI in
        # those paths.
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(snippet="There is no content on this slide."),
            {(None, 1): _unit_props(1)},
            {},
        )
        assert dto is None
        assert reason == "low_information"

    def test_negative_page_is_dropped_with_reason(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(page=-1), {(None, 1): _unit_props(1)}, {}
        )
        assert dto is None
        assert reason == "bad_page_or_ids"

    def test_slide_with_transcription_becomes_slide_video(self):
        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            _segment_props(unit_id=1, page=4),
            {(None, 1): _unit_props(1)},
            {(None, 1, 4): 125.0},
        )
        assert reason is None
        assert dto is not None
        assert dto.lecture_unit.source_type == "lecture_unit_slide_video"
        assert dto.lecture_unit.query_params["timestamp"] == 125.0

    def test_lecture_units_with_the_same_id_from_different_instances_do_not_collide(
        self,
    ):
        # Regression: keying by (base_url, unit_id) instead of the bare id — two
        # different Artemis instances sharing one Weaviate can have a lecture unit
        # with the same numeric id, and must not silently overwrite each other.
        units_by_id = {
            ("http://instance-a", 411): _unit_props(411, name="Instance A's unit"),
            ("http://instance-b", 411): _unit_props(
                411, name="Instance B's unrelated unit"
            ),
        }
        props = _segment_props(unit_id=411)
        props["base_url"] = "http://instance-a"

        dto, reason = LectureGlobalSearchRetrieval._segment_to_dto(
            props, units_by_id, {}
        )

        assert reason is None
        assert dto is not None
        assert dto.lecture_unit.name == "Instance A's unit"


class TestFetchLimitRegression:
    """Regressions in the metadata fetch: the over-fetch limit and the
    (base_url, id) keying that keeps colliding instances' rows distinct."""

    def test_metadata_fetch_limit_survives_duplicate_unit_ids(self):
        # Regression for the vanishing-answer bug: with limit=len(unit_ids),
        # duplicate rows from a shared Weaviate crowd out requested ids. The
        # fetch limit must leave generous headroom above the id count.
        for n_ids in (1, 5, 92):
            limit = max(100, n_ids * 10)
            assert limit >= n_ids * 2, "limit must tolerate duplicate rows per id"
            assert limit >= 100, "small requests must still over-fetch"

    def test_fetch_lecture_units_keeps_both_instances_rows_for_a_colliding_id(self):
        # Regression: two DIFFERENT Artemis instances sharing one Weaviate can each
        # have a lecture unit with the same numeric id (auto-increment ids restart
        # per database). Keying the result by the bare id let one instance's row
        # silently overwrite the other's, attaching the wrong instance's title/link
        # to a search hit. Keying by (base_url, id) must keep both.
        retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
        instance_0_unit = SimpleNamespace(
            properties={
                LectureUnitSchema.LECTURE_UNIT_ID.value: 411,
                LectureUnitSchema.BASE_URL.value: "http://localhost:8080",
                LectureUnitSchema.LECTURE_UNIT_NAME.value: "instance 0's unit",
            }
        )
        instance_6_unit = SimpleNamespace(
            properties={
                LectureUnitSchema.LECTURE_UNIT_ID.value: 411,
                LectureUnitSchema.BASE_URL.value: "http://localhost:8086",
                LectureUnitSchema.LECTURE_UNIT_NAME.value: "instance 6's unrelated unit",
            }
        )
        retrieval.lecture_unit_collection = Mock()
        retrieval.lecture_unit_collection.query.fetch_objects.return_value = Mock(
            objects=[instance_0_unit, instance_6_unit]
        )

        result = retrieval._fetch_lecture_units([411])

        assert len(result) == 2
        assert (
            result[("http://localhost:8080", 411)][
                LectureUnitSchema.LECTURE_UNIT_NAME.value
            ]
            == "instance 0's unit"
        )
        assert (
            result[("http://localhost:8086", 411)][
                LectureUnitSchema.LECTURE_UNIT_NAME.value
            ]
            == "instance 6's unrelated unit"
        )

    def test_fetch_lecture_units_sends_the_formula_limit_to_weaviate(self):
        # The formula test above only checks max(100, n_ids * 10) in isolation; a
        # regression that reverted the real call back to limit=len(unit_ids) (the
        # exact vanishing-answer bug this exists to prevent) would pass it and the
        # colliding-id test above unchanged, since that test's mock returns its
        # fixture objects regardless of what limit was requested.
        retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
        retrieval.lecture_unit_collection = Mock()
        retrieval.lecture_unit_collection.query.fetch_objects.return_value = Mock(
            objects=[]
        )

        unit_ids = list(range(92))
        retrieval._fetch_lecture_units(unit_ids)

        sent_limit = (
            retrieval.lecture_unit_collection.query.fetch_objects.call_args.kwargs[
                "limit"
            ]
        )
        assert sent_limit == max(100, len(unit_ids) * 10)


def test_retrieval_instruction_is_query_side_prefix():
    # The Qwen3 instruction must be a PREFIX applied to queries (asymmetric
    # retrieval); documents are embedded raw. Guard its shape so an accidental
    # reformat cannot silently break the trained scaffold.
    assert QWEN3_RETRIEVAL_INSTRUCTION.startswith("Instruct: ")
    assert QWEN3_RETRIEVAL_INSTRUCTION.endswith("Query: ")


def test_embed_retrieval_query_embeds_the_raw_query_when_no_instruction_is_configured():
    # A standard OpenAI/Azure embedding model (the oai-embedding-small default
    # included) has no instruction-tuned protocol to satisfy; folding the Qwen3
    # instruction into its query would just embed that text as query content.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval._retrieval_instruction = None
    retrieval.llm_embedding = Mock()

    retrieval.embed_retrieval_query("what is backpropagation")

    retrieval.llm_embedding.embed.assert_called_once_with("what is backpropagation")


def test_embed_retrieval_query_folds_the_configured_instruction():
    # Only a deployment that set retrieval_instruction on its embedding model
    # entry (an instruction-tuned model like Qwen3-Embedding) gets the fold.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval._retrieval_instruction = "Instruct: do the thing\nQuery: "
    retrieval.llm_embedding = Mock()

    retrieval.embed_retrieval_query("what is backpropagation")

    retrieval.llm_embedding.embed.assert_called_once_with(
        "Instruct: do the thing\nQuery: what is backpropagation"
    )


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
        side_effect=lambda collection, schema, ids, extra_filter=None: [
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


def test_expansion_restricts_the_transcription_lane_to_slide_less_segments():
    # A page-numbered transcription row is already represented by that page's
    # slide segment (see _search_video_transcriptions' own page_number == -1
    # filter for the identical reason); without the same restriction here, the
    # join pulls it in a second time as a duplicate "video-only" moment and
    # spends the per-unit expansion budget on content already shown once.
    key = ("http://a", 1, 10)
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.collection = object()
    retrieval.transcription_collection = object()
    retrieval._fetch_unit_objects = Mock(return_value=[])
    retrieval._fetch_metadata = Mock(return_value=({}, {}, {}))
    retrieval._map_candidates = Mock(return_value=[])

    retrieval._expand_by_unit(
        [_candidate(0.5, "anchor", key)],
        _SearchTelemetry(),
        _VisibilityPolicy.from_context(None),
    )

    calls = {
        call.args[0]: call for call in retrieval._fetch_unit_objects.call_args_list
    }
    segment_call = calls[retrieval.collection]
    transcription_call = calls[retrieval.transcription_collection]

    assert len(segment_call.args) == 3, "the segment lane keeps every page"
    assert (
        segment_call.kwargs.get("extra_filter") is None
    ), "a regression could pass extra_filter as a keyword and still keep len(args) == 3"
    assert transcription_call.args[3] == Filter.by_property(
        LectureTranscriptionSchema.PAGE_NUMBER.value
    ).equal(-1), "the transcription lane must skip rows a slide segment already covers"


def test_safe_rerank_scores_a_single_candidate_instead_of_skipping_it():
    # A single candidate must still be scored against the relevance floor — it
    # must not silently bypass reranking just because there is nothing to
    # compare it against for ordering purposes. The floor rejects GARBAGE
    # (see test_rerank_floor_keeps_weak_but_plausible_candidates); a lone
    # candidate that skips scoring entirely can never be rejected by it.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.reranker_model_id = "some-reranker"
    candidate = SimpleNamespace(snippet="a lone candidate")

    fake_client = Mock()
    fake_client.rerank.return_value = SimpleNamespace(
        results=[SimpleNamespace(index=0, relevance_score=0.01)]
    )
    with patch(
        "iris.retrieval.lecture.lecture_global_search_retrieval.LlmManager"
    ) as mock_manager_cls:
        mock_manager_cls.return_value.get_llm_by_id.return_value = fake_client
        result = retrieval._safe_rerank("irrelevant junk query", [candidate])

    assert result is not None, "a single candidate must still be scored, not skipped"
    _, relevance = result
    assert relevance == [0.01]


def test_empty_course_scope_still_returns_pre_authorized_entity_sources():
    # A user with entity-level access (e.g. a public channel or catalog entry)
    # but no role-based course access gets effective_course_ids == [] — the
    # lecture-content lanes have nothing to search, but entity_sources were
    # already authorized independently by Artemis (see _run_hybrid_search's
    # own docstring) and must not be discarded along with the content search.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.embed_retrieval_query = Mock(
        side_effect=AssertionError("must not embed when content lanes are skipped")
    )
    retrieval._run_hybrid_search = Mock(return_value=["entity result"])

    entity_sources = [EntitySourceDTO(entity_type="faq", snippet="A public FAQ answer")]
    result = retrieval.search(
        query="anything",
        limit=5,
        access_context=AccessContext(course_ids=[], unrestricted=False),
        entity_sources=entity_sources,
    )

    assert result == ["entity result"]
    retrieval._run_hybrid_search.assert_called_once()
    assert retrieval._run_hybrid_search.call_args.kwargs["skip_content_lanes"] is True
    assert (
        retrieval._run_hybrid_search.call_args.kwargs["entity_sources"]
        == entity_sources
    )


def test_empty_course_scope_with_no_entity_sources_still_returns_nothing():
    # The original short-circuit stays correct for the case it was actually
    # meant for: nothing accessible at all.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval._run_hybrid_search = Mock(
        side_effect=AssertionError("must not run the search pipeline for nothing")
    )

    result = retrieval.search(
        query="anything",
        limit=5,
        access_context=AccessContext(course_ids=[], unrestricted=False),
        entity_sources=None,
    )

    assert result == []


def test_lane_expands_past_a_full_window_of_filtered_hits_to_reach_a_visible_one():
    # Release-date/visibility filtering happens AFTER retrieval, so a fixed
    # 25-row window can be entirely unreleased or hidden while a visible,
    # relevant result sits at position 26+. The first fetch returns a FULL
    # window (signalling more may exist) that filters down to nothing; the
    # search must double the depth and retry rather than stopping there.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    visible = _candidate(0.8, "visible content", ("http://a", 1, 10))

    retrieval._search_lanes = Mock(
        side_effect=[
            ([SimpleNamespace()] * 25, []),  # full window: maybe more exist
            ([SimpleNamespace()] * 30, []),  # wider fetch: the visible hit
        ]
    )
    retrieval._fetch_metadata = Mock(return_value=({}, {}, {}))
    retrieval._map_candidates = Mock(side_effect=[[], [visible]])

    result = retrieval._search_lanes_until_visible(
        query="anything",
        vector=[0.1],
        alpha=0.75,
        limit=5,
        course_ids=None,
        exclude_course_ids=None,
        auto_cut=False,
        policy=_VisibilityPolicy.from_context(None),
        telemetry=_SearchTelemetry(),
    )

    assert result == [visible]
    assert retrieval._search_lanes.call_count == 2
    first_depth = retrieval._search_lanes.call_args_list[0].args[3]
    second_depth = retrieval._search_lanes.call_args_list[1].args[3]
    assert (first_depth, second_depth) == (25, 50)


def test_autocut_shortened_lane_retries_at_the_same_depth_without_autocut_first():
    # auto_cut (the answer path) can make Weaviate stop a lane at a natural score
    # cliff well short of lane_depth — a quality signal, not evidence the lane is
    # exhausted. If everything above that cliff turns out hidden or unreleased,
    # the search must drop autocut and retry the SAME depth with the fixed limit
    # before trusting the length-based exhaustion check, since a visible result
    # autocut excluded outright can sit right below that cliff.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    visible = _candidate(0.8, "visible content", ("http://a", 1, 10))

    retrieval._search_lanes = Mock(
        side_effect=[
            ([SimpleNamespace()] * 3, []),  # autocut stopped early at a score cliff
            ([SimpleNamespace()] * 25, []),  # same depth, no autocut: the full window
        ]
    )
    retrieval._fetch_metadata = Mock(return_value=({}, {}, {}))
    retrieval._map_candidates = Mock(side_effect=[[], [visible]])

    result = retrieval._search_lanes_until_visible(
        query="anything",
        vector=[0.1],
        alpha=0.75,
        limit=1,
        course_ids=None,
        exclude_course_ids=None,
        auto_cut=True,
        policy=_VisibilityPolicy.from_context(None),
        telemetry=_SearchTelemetry(),
    )

    assert result == [visible]
    assert retrieval._search_lanes.call_count == 2
    first_depth, first_autocut = (
        retrieval._search_lanes.call_args_list[0].args[3],
        retrieval._search_lanes.call_args_list[0].args[6],
    )
    second_depth, second_autocut = (
        retrieval._search_lanes.call_args_list[1].args[3],
        retrieval._search_lanes.call_args_list[1].args[6],
    )
    assert (first_depth, first_autocut) == (25, True)
    assert (second_depth, second_autocut) == (25, False)


def test_lane_stops_expanding_once_a_lane_is_exhausted():
    # Fewer hits than requested means Weaviate has nothing more to offer;
    # retrying further would just repeat the same (still-filtered) result.
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval._search_lanes = Mock(return_value=([SimpleNamespace()] * 3, []))
    retrieval._fetch_metadata = Mock(return_value=({}, {}, {}))
    retrieval._map_candidates = Mock(return_value=[])

    result = retrieval._search_lanes_until_visible(
        query="anything",
        vector=[0.1],
        alpha=0.75,
        limit=5,
        course_ids=None,
        exclude_course_ids=None,
        auto_cut=False,
        policy=_VisibilityPolicy.from_context(None),
        telemetry=_SearchTelemetry(),
    )

    assert not result
    retrieval._search_lanes.assert_called_once()


class TestCourseScopeFilter:
    """course_ids and exclude_course_ids are independent, additive constraints:
    an unrestricted caller has no course_ids ceiling to narrow locally, so
    Artemis sends only exclusions, which must still reach the Weaviate query."""

    def test_no_constraints_produces_no_filter(self):
        assert _course_scope_filter("course_id", None, None) is None
        assert _course_scope_filter("course_id", [], []) is None

    def test_only_inclusion_produces_a_contains_any_filter(self):
        result = _course_scope_filter("course_id", [9, 11], None)
        assert result.operator.value == "ContainsAny"
        assert result.value == [9, 11]

    def test_only_exclusion_produces_a_contains_none_filter(self):
        # The scenario this exists for: an unrestricted caller with no course_ids
        # ceiling for Artemis to narrow itself, so the exclusion must reach the
        # query on its own rather than being dropped for lack of a course_ids list.
        result = _course_scope_filter("course_id", None, [5])
        assert result.operator.value == "ContainsNone"
        assert result.value == [5]

    def test_both_constraints_combine_with_and(self):
        result = _course_scope_filter("course_id", [9, 11], [5])
        assert result.operator.value == "And"
        sub_operators = {f.operator.value for f in result.filters}
        assert sub_operators == {"ContainsAny", "ContainsNone"}


def test_search_segments_applies_the_exclusion_filter_with_no_course_ids():
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.collection = Mock()
    retrieval.collection.query.hybrid.return_value = Mock(objects=[])

    retrieval._search_segments(
        query="anything",
        vector=[0.1],
        alpha=0.75,
        limit=25,
        course_ids=None,
        exclude_course_ids=[5],
    )

    sent_filter = retrieval.collection.query.hybrid.call_args.kwargs["filters"]
    assert sent_filter is not None
    assert sent_filter.operator.value == "ContainsNone"
    assert sent_filter.value == [5]
