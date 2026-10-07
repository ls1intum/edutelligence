"""Request instance identity is exact even with word-tokenized URL filters."""

# pylint: disable=protected-access

import copy
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from iris.config import settings
from iris.domain.search.global_search_dto import (
    AccessContext,
    EntitySourceDTO,
    GlobalSearchRequestDTO,
    LectureSearchRequestDTO,
)
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline, SearchIntent
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
    _Candidate,
    _SearchTelemetry,
    _VisibilityPolicy,
)
from iris.vector_database.lecture_unit_segment_schema import LectureUnitSegmentSchema
from iris.web.routers import pipelines as pipelines_router
from iris.web.routers import search as search_router

MAIN = "https://artemis.tum.de"
STAGING = "https://artemis-staging1.tum.de"
SETTINGS = {
    "authenticationToken": "test-token",  # pragma: allowlist secret
    "artemisBaseUrl": MAIN,
    "pyrisVersion": "test",
    "variant": "default",
}
ROLES = [
    None,
    AccessContext(course_ids=[30], student_course_ids=[30]),
    AccessContext(course_ids=[30], editor_course_ids=[30], staff_course_ids=[30]),
    AccessContext(course_ids=[30], ta_course_ids=[30], staff_course_ids=[30]),
    AccessContext(course_ids=[30], staff_course_ids=[30]),
    AccessContext(unrestricted=True),
]
FOREIGN_TAGS = [
    STAGING,
    "https://tum.artemis.de",
    "https://artemis-tum.de",
    "https://ARTEMIS.tum.de",
    "https://artemis.tum.de/",
    "https://artemis.tum.de/path",
    "https://artemis.tum.de:443",
    "http://artemis.tum.de",
    None,
    "",
    42,
    [MAIN],
]


def _tokens(value):
    return set(re.findall(r"\w+", value.lower()))


def _matches(filter_value, props):
    """Equal(text) matches query tokens, not byte-for-byte URLs."""
    if filter_value is None:
        return True
    operator = filter_value.operator.value
    if operator == "And":
        return all(_matches(child, props) for child in filter_value.filters)
    value = props.get(filter_value.target)
    expected = filter_value.value
    if operator == "Equal":
        if isinstance(expected, str):
            return isinstance(value, str) and _tokens(expected) <= _tokens(value)
        return value == expected
    if operator == "ContainsAny":
        return value in expected
    if operator == "ContainsNone":
        return value not in expected
    raise AssertionError(f"Unexpected filter operator: {operator}")


class _WordQuery:
    """Read-only collection fake with the existing URL tokenization semantics."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _fetch(self, **kwargs):
        self.calls.append(kwargs)
        rows = [
            row for row in self.rows if _matches(kwargs.get("filters"), row.properties)
        ]
        return SimpleNamespace(objects=copy.deepcopy(rows[: kwargs["limit"]]))

    def hybrid(self, **kwargs):
        return self._fetch(**kwargs)

    def fetch_objects(self, **kwargs):
        return self._fetch(**kwargs)


def _row(base_url=MAIN, unit_id=10, page=1, score=0.9, **overrides):
    props = {
        "base_url": base_url,
        "course_id": 30,
        "lecture_id": 20,
        "lecture_unit_id": unit_id,
        "page_number": page,
        "segment_summary": "Owned explanation of how stack operations work.",
        "segment_text": "Owned explanation of how stack operations work.",
        "segment_start_time": 12.0,
    }
    props.update(overrides)
    return SimpleNamespace(properties=props, metadata=SimpleNamespace(score=score))


def _unit(base_url=MAIN, unit_id=10, **overrides):
    props = {
        "base_url": base_url,
        "course_id": 30,
        "lecture_id": 20,
        "lecture_unit_id": unit_id,
        "course_name": "Owned course",
        "lecture_name": "Owned lecture",
        "lecture_unit_name": "Owned unit",
        "release_date": None,
    }
    props.update(overrides)
    return SimpleNamespace(properties=props)


def _retriever(segments=None, transcriptions=None, units=None, chunks=None):
    retrieval = object.__new__(LectureGlobalSearchRetrieval)
    retrieval.embed_retrieval_query = Mock(return_value=[0.1, 0.2])
    retrieval.collection = SimpleNamespace(query=_WordQuery(segments or []))
    retrieval.transcription_collection = SimpleNamespace(
        query=_WordQuery(transcriptions or [])
    )
    retrieval.lecture_unit_collection = SimpleNamespace(query=_WordQuery(units or []))
    retrieval.page_chunk_collection = SimpleNamespace(query=_WordQuery(chunks or []))
    retrieval._safe_rerank = Mock(return_value=None)
    return retrieval


@pytest.mark.parametrize("context", ROLES)
@pytest.mark.parametrize("foreign_url", FOREIGN_TAGS)
def test_foreign_higher_scoring_duplicate_never_suppresses_owned_result(
    context, foreign_url
):
    foreign = _row(foreign_url, score=1.0)
    if foreign_url is None:
        del foreign.properties["base_url"]
    retrieval = _retriever(
        segments=[foreign, _row()],
        units=[_unit(foreign_url, lecture_unit_name="Foreign unit"), _unit()],
    )
    results = retrieval.search("stack", 5, base_url=MAIN, access_context=context)
    assert [result.lecture_unit.id for result in results] == [10]
    assert results[0].lecture_unit.name == "Owned unit"
    for candidate in retrieval._safe_rerank.call_args.args[1]:
        assert candidate.lecture_unit.name == "Owned unit"


@pytest.mark.parametrize("requested,other", [(MAIN, STAGING), (STAGING, MAIN)])
def test_both_match_directions_preserve_exact_owned_results(requested, other):
    retrieval = _retriever(
        segments=[_row(other, unit_id=11), _row(requested)],
        units=[_unit(other, unit_id=11), _unit(requested)],
    )
    assert [
        r.lecture_unit.id for r in retrieval.search("stack", 5, base_url=requested)
    ] == [10]


@pytest.mark.parametrize("context", ROLES)
@pytest.mark.parametrize("url", [None, "", " \t\n", 42])
def test_missing_or_invalid_scope_fails_before_any_search_or_embedding(context, url):
    retrieval = _retriever()
    with pytest.raises(ValueError):
        retrieval.search("stack", 5, base_url=url, access_context=context)
    retrieval.embed_retrieval_query.assert_not_called()
    assert not retrieval.collection.query.calls


@pytest.mark.parametrize("url", [None, "", " \t", 42])
def test_sync_and_async_request_validation_rejects_invalid_scope(url):
    with pytest.raises(ValidationError):
        LectureSearchRequestDTO(query="stack", artemisBaseUrl=url)
    with pytest.raises(ValidationError):
        GlobalSearchRequestDTO(
            query="stack", settings={**SETTINGS, "artemisBaseUrl": url}
        )


def test_missing_sync_scope_is_rejected_and_raw_url_is_preserved():
    with pytest.raises(ValidationError):
        LectureSearchRequestDTO(query="stack")
    url = MAIN + "/"
    assert (
        LectureSearchRequestDTO(query="stack", artemisBaseUrl=url).artemis_base_url
        == url
    )
    assert (
        GlobalSearchRequestDTO(
            query="stack", settings={**SETTINGS, "artemisBaseUrl": url}
        ).settings.artemis_base_url
        == url
    )


@pytest.mark.parametrize("url", [None, "", " \t", 42])
def test_pipeline_rejects_invalid_identity_before_classification(url):
    pipeline = object.__new__(GlobalSearchPipeline)
    with patch("iris.pipeline.global_search_pipeline.classify_intent") as classify:
        with pytest.raises(ValueError):
            pipeline("stack", base_url=url)
        classify.assert_not_called()


def test_internal_retrieval_cannot_create_an_unscoped_policy():
    retrieval = _retriever()
    with pytest.raises(ValueError, match="instance-scoped"):
        retrieval._run_hybrid_search("stack", [0.1], 0.5, 5)
    assert not retrieval.collection.query.calls


@pytest.mark.parametrize("auto_cut", [False, True])
def test_saturated_foreign_lane_expands_using_raw_count_before_filtering(auto_cut):
    foreign = [_row(STAGING, unit_id=i, score=1.0) for i in range(30)]
    retrieval = _retriever(segments=[*foreign, _row()], units=[_unit()])
    with patch.object(settings, "global_search_expand_units", False):
        results = retrieval.search("stack", 1, base_url=MAIN, auto_cut=auto_cut)
    assert [r.lecture_unit.id for r in results] == [10]
    depths = [call["limit"] for call in retrieval.collection.query.calls]
    assert depths == ([25, 25, 50] if auto_cut else [25, 50])


def test_foreign_lane_reaches_cap_and_records_rejected_candidates():
    retrieval = _retriever(segments=[_row(STAGING)] * 100)
    telemetry = _SearchTelemetry()
    with patch.object(settings, "global_search_lane_depth_max", 50):
        result = retrieval._search_lanes_until_visible(
            "stack",
            [0.1],
            0.5,
            1,
            None,
            None,
            False,
            _VisibilityPolicy.from_context(None, base_url=MAIN),
            telemetry,
        )
    assert not result
    assert [call["limit"] for call in retrieval.collection.query.calls] == [25, 50]
    assert telemetry.drop_counts["content_foreign_instance"] == 50
    assert not retrieval.lecture_unit_collection.query.calls


def test_metadata_joins_and_expansion_reject_token_matching_foreign_rows():
    retrieval = _retriever(
        segments=[
            _row(),
            _row(
                unit_id=10,
                page=2,
                segment_summary="Owned sibling explains push and pop.",
            ),
            _row(STAGING, page=3, segment_summary="Foreign sibling."),
        ],
        transcriptions=[
            _row(STAGING, page=1, segment_start_time=1.0),
            _row(page=1, segment_start_time=12.0),
        ],
        units=[_unit(STAGING, lecture_unit_name="Foreign unit"), _unit()],
        chunks=[
            _row(
                STAGING,
                page=1,
                display_page_number=1,
                hidden_until="2099-01-01T00:00:00Z",
            ),
            _row(page=1, display_page_number=1),
        ],
    )
    before = copy.deepcopy(
        [
            collection.query.rows
            for collection in (
                retrieval.collection,
                retrieval.transcription_collection,
                retrieval.lecture_unit_collection,
                retrieval.page_chunk_collection,
            )
        ]
    )
    units = retrieval._fetch_lecture_units([10], base_url=MAIN)
    assert set(units) == {(MAIN, 10)}
    assert retrieval._fetch_transcription_start_times([(10, 1)], base_url=MAIN) == {
        (MAIN, 10, 1): 12.0
    }
    slides = retrieval._fetch_slides_by_display_page([10], base_url=MAIN)
    assert len(slides[(MAIN, 10, 1)]) == 1
    assert slides[(MAIN, 10, 1)][0]["base_url"] == MAIN
    with patch.object(settings, "global_search_expand_units", True):
        results = retrieval.search("stack", 1, base_url=MAIN, auto_cut=True)
    assert {r.snippet for r in results} == {
        "Owned explanation of how stack operations work.",
        "Owned sibling explains push and pop.",
    }
    assert before == [
        collection.query.rows
        for collection in (
            retrieval.collection,
            retrieval.transcription_collection,
            retrieval.lecture_unit_collection,
            retrieval.page_chunk_collection,
        )
    ]


@pytest.mark.parametrize("context", ROLES)
@pytest.mark.parametrize("foreign_url", FOREIGN_TAGS)
def test_direct_mapping_and_release_bypass_require_exact_ownership(
    context, foreign_url
):
    policy = _VisibilityPolicy.from_context(context, base_url=MAIN)
    foreign = _row(foreign_url).properties
    metadata = {(STAGING, 10): _unit(STAGING).properties}
    assert LectureGlobalSearchRetrieval._segment_to_dto(
        foreign, metadata, {}, policy
    ) == (None, "foreign_instance")
    assert LectureGlobalSearchRetrieval._transcription_to_dto(
        foreign, metadata, policy=policy
    ) == (None, "foreign_instance")
    assert not policy.release_bypassed(30, foreign)
    assert LectureGlobalSearchRetrieval._segment_to_dto(_row().properties, {}, {}) == (
        None,
        "missing_instance_scope",
    )


def test_staff_bypass_is_retained_only_for_own_unreleased_unit():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    retrieval = _retriever(
        segments=[_row(STAGING), _row()],
        units=[_unit(STAGING, release_date=future), _unit(release_date=future)],
    )
    results = retrieval.search(
        "stack",
        5,
        base_url=MAIN,
        access_context=AccessContext(course_ids=[30], staff_course_ids=[30]),
    )
    assert [r.lecture_unit.id for r in results] == [10]


@pytest.mark.parametrize("mapper", ["_segment_to_dto", "_transcription_to_dto"])
def test_mapping_rejects_foreign_metadata_under_an_owned_lookup_key(mapper):
    policy = _VisibilityPolicy.from_context(
        AccessContext(unrestricted=True), base_url=MAIN
    )
    metadata = {(MAIN, 10): _unit(STAGING).properties}
    convert = getattr(LectureGlobalSearchRetrieval, mapper)
    assert convert(_row().properties, metadata, {}, policy) == (
        None,
        "foreign_instance",
    )
    assert convert(_row().properties, metadata, {}) == (
        None,
        "missing_instance_scope",
    )


def test_pre_authorized_entity_pool_survives_empty_course_scope():
    retrieval = _retriever()
    entity = EntitySourceDTO(entity_type="faq", snippet="An authorized FAQ.")
    assert retrieval.search(
        "stack",
        5,
        base_url=MAIN,
        access_context=AccessContext(course_ids=[]),
        entity_sources=[entity],
    ) == [entity]
    retrieval.embed_retrieval_query.assert_not_called()


def test_sync_route_and_all_pipeline_retrieval_calls_forward_exact_url():
    url = MAIN + "/"
    dto = LectureSearchRequestDTO(query="stack", artemisBaseUrl=url)
    with (
        patch.object(search_router, "VectorDatabase"),
        patch.object(search_router, "LectureGlobalSearchRetrieval") as constructor,
    ):
        constructor.return_value.search.return_value = []
        search_router._traced_lecture_search(dto)
        assert constructor.return_value.search.call_args.kwargs["base_url"] == url
    pipeline = object.__new__(GlobalSearchPipeline)
    pipeline.retriever = Mock()
    pipeline.retriever.search.return_value = []
    pipeline("stack", intent=SearchIntent.SKIP_AI, base_url=url)
    assert pipeline.retriever.search.call_args.kwargs["base_url"] == url
    pipeline.retriever.reset_mock()
    pipeline._retrieve_sources("stack", 5, base_url=url)
    assert [
        call.kwargs["alpha"] for call in pipeline.retriever.search.call_args_list
    ] == [0.5, 0.1]
    assert all(
        call.kwargs["base_url"] == url
        for call in pipeline.retriever.search.call_args_list
    )


@pytest.mark.parametrize("intent", [SearchIntent.SKIP_AI, SearchIntent.TRIGGER_AI])
def test_async_worker_passes_settings_identity_in_both_intent_paths(intent):
    dto = GlobalSearchRequestDTO(query="stack", settings=SETTINGS)
    with (
        patch.object(pipelines_router, "classify_intent", return_value=intent),
        patch.object(pipelines_router, "VectorDatabase"),
        patch.object(pipelines_router, "GlobalSearchCallback") as callback,
        patch.object(pipelines_router, "LectureGlobalSearchRetrieval") as retriever,
        patch.object(pipelines_router, "GlobalSearchPipeline") as pipeline,
    ):
        retriever.return_value.search.return_value = []
        pipeline.return_value.return_value = SimpleNamespace(
            answer=None, sources=[], entity_sources=[], citation_source_types=[]
        )
        pipelines_router.run_global_search_pipeline_worker(dto, "scope-test")
        callback.return_value.finish.assert_called_once()
        call = (
            retriever.return_value.search.call_args
            if intent == SearchIntent.SKIP_AI
            else pipeline.return_value.call_args
        )
        assert call.kwargs["base_url"] == MAIN


def _anchor(unit_id, snippet):
    return _Candidate(0.9, SimpleNamespace(snippet=snippet), (MAIN, 30, unit_id))


def test_capped_expansion_fetches_highest_owned_anchor_before_storage_order():
    retrieval = _retriever(
        segments=[
            _row(unit_id=10, segment_summary="Lower anchor's owned sibling."),
            _row(unit_id=11, segment_summary="Top anchor's owned sibling."),
        ],
        units=[_unit(unit_id=10), _unit(unit_id=11)],
    )
    anchors = [_anchor(11, "Top video anchor."), _anchor(10, "Lower video anchor.")]
    with patch.object(settings, "global_search_expand_fetch_limit", 1):
        result = retrieval._expand_by_unit(
            anchors,
            _SearchTelemetry(),
            _VisibilityPolicy.from_context(None, base_url=MAIN),
        )
    assert [candidate.dto.snippet for candidate in result] == [
        "Top video anchor.",
        "Lower video anchor.",
        "Top anchor's owned sibling.",
    ]
    calls = retrieval.collection.query.calls
    assert len(calls) == 1
    filters = {part.target: part.value for part in calls[0]["filters"].filters}
    assert filters == {"base_url": MAIN, "course_id": 30, "lecture_unit_id": 11}
    assert calls[0]["limit"] == 1


def test_empty_anchor_costs_no_raw_budget_and_never_sends_zero_limit():
    retrieval = _retriever(segments=[_row(unit_id=10)])
    with patch.object(settings, "global_search_expand_fetch_limit", 1):
        rows = retrieval._fetch_unit_objects(
            retrieval.collection,
            LectureUnitSegmentSchema,
            [(MAIN, 30, 99), (MAIN, 30, 10), (MAIN, 30, 11)],
            base_url=MAIN,
        )
    assert [row.properties["lecture_unit_id"] for row in rows] == [10]
    assert [call["limit"] for call in retrieval.collection.query.calls] == [1, 1]
    with patch.object(settings, "global_search_expand_fetch_limit", 0):
        assert not retrieval._fetch_unit_objects(
            retrieval.collection,
            LectureUnitSegmentSchema,
            [(MAIN, 30, 10)],
            base_url=MAIN,
        )
    assert len(retrieval.collection.query.calls) == 2


def test_expansion_rejects_wrong_owner_and_incomplete_structural_keys_before_query():
    retrieval = _retriever(segments=[_row()])
    rows = retrieval._fetch_unit_objects(
        retrieval.collection,
        LectureUnitSegmentSchema,
        [(STAGING, 30, 10), (MAIN, None, 10), (MAIN, 30, None), (MAIN, 30, 10)],
        base_url=MAIN,
    )
    assert [row.properties["lecture_unit_id"] for row in rows] == [10]
    assert len(retrieval.collection.query.calls) == 1


def test_foreign_clone_spends_raw_budget_but_never_enters_expanded_output():
    retrieval = _retriever(
        segments=[_row(STAGING, unit_id=11), _row(unit_id=11)],
        units=[_unit(unit_id=11)],
    )
    anchors = [_anchor(11, "An already authorized video anchor.")]
    with patch.object(settings, "global_search_expand_fetch_limit", 1):
        result = retrieval._expand_by_unit(
            anchors,
            _SearchTelemetry(),
            _VisibilityPolicy.from_context(None, base_url=MAIN),
        )
    assert result == anchors
    assert len(retrieval.collection.query.calls) == 1
    assert not retrieval.lecture_unit_collection.query.calls


def test_unsaturated_expansion_matches_union_and_bounds_queries_by_selected_anchors():
    rows = [
        _row(
            unit_id=unit,
            segment_summary=f"Owned sibling for unit {unit} explains stack behavior.",
        )
        for unit in range(10, 16)
    ]
    retrieval = _retriever(
        segments=rows, units=[_unit(unit_id=unit) for unit in range(10, 16)]
    )
    anchors = [_anchor(unit, f"Video anchor {unit}.") for unit in range(10, 16)]
    with (
        patch.object(settings, "global_search_expand_max_units", 3),
        patch.object(settings, "global_search_expand_fetch_limit", 100),
    ):
        result = retrieval._expand_by_unit(
            anchors,
            _SearchTelemetry(),
            _VisibilityPolicy.from_context(None, base_url=MAIN),
        )
    selected = {10, 11, 12}
    expected = {
        row.properties["segment_summary"]
        for row in rows
        if row.properties["lecture_unit_id"] in selected
    }
    # Every raw row in the unsaturated union is returned by the disjoint full-key queries.
    anchor_count = len(anchors)
    siblings = result[anchor_count:]
    assert {candidate.dto.snippet for candidate in siblings} == expected
    assert len(retrieval.collection.query.calls) == 3
    expansion_calls = [
        call
        for call in retrieval.transcription_collection.query.calls
        if any(
            part.target == "lecture_unit_id" and part.operator.value == "Equal"
            for part in call["filters"].filters
        )
    ]
    assert len(expansion_calls) == 3
    assert [
        next(
            part.value
            for part in call["filters"].filters
            if part.target == "lecture_unit_id"
        )
        for call in expansion_calls
    ] == [10, 11, 12]


def test_expansion_query_failure_propagates_without_partial_success():
    retrieval = _retriever()
    retrieval.collection.query.fetch_objects = Mock(
        side_effect=RuntimeError("read failed")
    )
    with pytest.raises(RuntimeError, match="read failed"):
        retrieval._fetch_unit_objects(
            retrieval.collection,
            LectureUnitSegmentSchema,
            [(MAIN, 30, 10)],
            base_url=MAIN,
        )
