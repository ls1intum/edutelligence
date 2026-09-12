"""Unit tests for entity candidates in the global-search answer path:
card rendering, wire shapes, the shared rerank pool, representation slots,
the pointer tier, and the pipeline's context labeling."""

# pylint: disable=protected-access

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from iris.domain.search.global_search_dto import (
    AccessContext,
    CourseInfo,
    EntityCandidateDTO,
    EntitySourceDTO,
    GlobalSearchRequestDTO,
    GlobalSearchResponseDTO,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.domain.status.global_search_status_update_dto import (
    GlobalSearchStatusUpdateDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum
from iris.pipeline.global_search_pipeline import (
    GlobalSearchPipeline,
    _source_label,
    _today_line,
)
from iris.pipeline.shared.entity_card_renderer import (
    is_pointer_candidate,
    render_entity_card,
)
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
    _Candidate,
    _is_entity,
    _SearchTelemetry,
    dedupe_semester_twins,
)

_SETTINGS_JSON = {
    "authenticationToken": "t",
    "artemisBaseUrl": "http://a",
    "variant": "default",
}


def _candidate_dto(**overrides) -> EntityCandidateDTO:
    payload = {"entityType": "exercise", "title": "RNN and LSTM Fundamentals"}
    payload.update(overrides)
    return EntityCandidateDTO(**payload)


def _entity_source(title="RNN quiz", etype="exercise"):
    return EntitySourceDTO(
        entity_type=etype,
        entity_id=1,
        course=CourseInfo(id=11, name="Test course"),
        title=title,
        snippet=f"{etype.capitalize()}: '{title}' in course 'Test course'.",
    )


def _content(snippet="A slide summary long enough to keep."):
    return SimpleNamespace(snippet=snippet)


def _retrieval() -> LectureGlobalSearchRetrieval:
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    retrieval.reranker_model_id = "reranker"
    return retrieval


# ---------------------------------------------------------------- card renderer


class TestEntityCardRenderer:
    """Verbalization of entity rows into reranker/LLM-readable cards."""

    def test_verbalizes_dates_points_and_duration(self):
        card = render_entity_card(
            _candidate_dto(
                exerciseType="quiz",
                courseName="Test course",
                dueDate=datetime(2026, 5, 17, 18, 24, tzinfo=timezone.utc),
                maxPoints=4,
                quizDurationSeconds=600,
            )
        )
        assert "Quiz exercise: 'RNN and LSTM Fundamentals'" in card
        assert "in course 'Test course'" in card
        assert "due Sunday, 17 May 2026 at 18:24 UTC" in card
        assert "worth 4 points" in card
        assert "quiz duration 10 minutes" in card

    def test_pointer_card_states_coverage_relation(self):
        card = render_entity_card(
            _candidate_dto(entityType="lecture_unit", title="W02U04 Mediator pattern")
        )
        assert "cover the topic named in its title" in card

    def test_description_replaces_the_coverage_line(self):
        card = render_entity_card(_candidate_dto(description="Implement sorting."))
        assert "Implement sorting." in card
        assert "cover the topic named in its title" not in card

    def test_channel_card_names_visibility_and_purpose(self):
        card = render_entity_card(
            _candidate_dto(
                entityType="channel", title="tech-support", channelIsPublic=True
            )
        )
        assert "public discussion channel" in card

    def test_card_is_never_empty(self):
        assert render_entity_card(EntityCandidateDTO(entityType="exam"))

    def test_pointer_detection(self):
        assert is_pointer_candidate(_candidate_dto())
        assert not is_pointer_candidate(_candidate_dto(description="text"))
        assert not is_pointer_candidate(_candidate_dto(entityType="channel"))


# ------------------------------------------------------------------ wire shapes


class TestWireShapes:
    """Additive wire compatibility for requests, responses and status DTOs."""

    def test_request_without_entity_candidates_is_a_no_op(self):
        dto = GlobalSearchRequestDTO(
            query="q", settings=_SETTINGS_JSON  # old-Artemis request shape
        )
        assert dto.entity_candidates == []

    def test_request_parses_camel_case_entity_candidates(self):
        dto = GlobalSearchRequestDTO(
            query="q",
            settings=_SETTINGS_JSON,
            entityCandidates=[
                {
                    "entityType": "exercise",
                    "courseId": 11,
                    "courseName": "Test course",
                    "dueDate": "2026-05-17T18:24:00Z",
                    "maxPoints": 4,
                }
            ],
        )
        candidate = dto.entity_candidates[0]
        assert candidate.course_id == 11
        assert candidate.due_date.year == 2026
        assert candidate.max_points == 4

    def test_response_never_serializes_the_pointer_tier_flag(self):
        source = _entity_source()
        source.via_pointer_tier = True
        response = GlobalSearchResponseDTO(
            answer="a", sources=[], entity_sources=[source]
        )
        data = response.model_dump(by_alias=True)
        assert data["entitySources"][0]["entityType"] == "exercise"
        assert "via_pointer_tier" not in data["entitySources"][0]
        assert "viaPointerTier" not in data["entitySources"][0]

    def test_status_update_carries_entity_sources_by_alias(self):
        status = GlobalSearchStatusUpdateDTO(
            run_state=RunStateEnum.FINISHED, entity_sources=[_entity_source()]
        )
        data = status.model_dump(by_alias=True)
        assert len(data["entitySources"]) == 1


# ------------------------------------------------------- rerank pool and gating


class TestEntityRerankGate:
    """Entity cards in the shared rerank pool: floor, slots, pointer tier."""

    def _gate(self, retrieval, deduped, entity_pool, relevance, limit=5):
        retrieval._safe_rerank = Mock(return_value=(1.0, relevance))
        telemetry = _SearchTelemetry()
        kept = retrieval._rerank_and_gate(
            "q", deduped, limit, True, telemetry, entity_pool
        )
        return kept, telemetry

    def test_entities_rank_on_the_shared_scale(self):
        retrieval = _retrieval()
        deduped = [_Candidate(0.9, _content("c1"), (None, 1, 1))]
        entity_pool = [_Candidate(0.0, _entity_source(), (None, None, None))]
        kept, telemetry = self._gate(retrieval, deduped, entity_pool, [0.2, 0.6])
        assert _is_entity(kept[0]) and kept[0].score == 0.6
        assert kept[1].score == 0.2
        assert telemetry.entity_kept == 1

    def test_representation_appends_crowded_out_entity(self):
        retrieval = _retrieval()
        deduped = [
            _Candidate(0.0, _content(f"content {i}"), (None, 1, i)) for i in range(7)
        ]
        entity_pool = [_Candidate(0.0, _entity_source(), (None, None, None))]
        # 7 content candidates outscore the entity; limit 5 would crowd it out
        relevance = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3]
        kept, _ = self._gate(retrieval, deduped, entity_pool, relevance)
        assert len(kept) == 6
        assert _is_entity(kept[-1])

    def test_pointer_tier_offers_top_entities_when_floor_empties(self):
        # The numeric floor judges "answers the question"; whether material is
        # ABOUT the topic is judged downstream by the navigate prompt, so even
        # low-scoring entity cards are offered (capped) instead of silence.
        retrieval = _retrieval()
        deduped = [_Candidate(0.0, _content(), (None, 1, 1))]
        entity_pool = [_Candidate(0.0, _entity_source(), (None, None, None))]
        kept, telemetry = self._gate(retrieval, deduped, entity_pool, [0.05, 0.035])
        assert len(kept) == 1 and _is_entity(kept[0])
        assert telemetry.pointer_tier
        assert kept[0].dto.via_pointer_tier

    def test_pointer_tier_joins_surviving_content_when_no_entity_clears_the_floor(self):
        # Weak-but-topical content above the floor must not suppress the
        # pointer tier: the student's real target may be a below-floor card,
        # since a unit that NAMES the topic never "answers" a what-is question.
        retrieval = _retrieval()
        deduped = [_Candidate(0.0, _content(), (None, 1, 1))]
        entity_pool = [
            _Candidate(0.0, _entity_source(title=f"e{i}"), (None, None, None))
            for i in range(4)
        ]
        relevance = [0.5, 0.01, 0.04, 0.02, 0.03]
        kept, telemetry = self._gate(retrieval, deduped, entity_pool, relevance)
        assert not _is_entity(kept[0]) and kept[0].score == 0.5
        assert [c.dto.title for c in kept[1:]] == ["e1", "e3", "e2"]
        assert all(c.dto.via_pointer_tier for c in kept[1:])
        assert telemetry.pointer_tier and telemetry.entity_kept == 3

    def test_pointer_tier_caps_the_offered_entities_and_keeps_rank_order(self):
        retrieval = _retrieval()
        deduped = [_Candidate(0.0, _content(), (None, 1, 1))]
        entity_pool = [
            _Candidate(0.0, _entity_source(title=f"e{i}"), (None, None, None))
            for i in range(5)
        ]
        relevance = [0.05, 0.01, 0.04, 0.02, 0.03, 0.05]
        kept, _ = self._gate(retrieval, deduped, entity_pool, relevance)
        assert [c.dto.title for c in kept] == ["e4", "e1", "e3"]  # top 3 by score

    def test_pointer_tier_stays_silent_without_entities(self):
        retrieval = _retrieval()
        deduped = [_Candidate(0.0, _content(), (None, 1, 1))]
        kept, telemetry = self._gate(retrieval, deduped, [], [0.05])
        assert kept == []
        assert not telemetry.pointer_tier

    def test_fused_fallback_keeps_capped_entities(self):
        # A rerank timeout must not erase the entity ladder: entities join the
        # context in prefetch order (capped) and the answer model judges them.
        retrieval = _retrieval()
        retrieval._safe_rerank = Mock(return_value=None)
        deduped = [_Candidate(0.9, _content(), (None, 1, 1))]
        entity_pool = [
            _Candidate(0.0, _entity_source(title=f"e{i}"), (None, None, None))
            for i in range(4)
        ]
        telemetry = _SearchTelemetry()
        kept = retrieval._rerank_and_gate("q", deduped, 5, True, telemetry, entity_pool)
        assert kept[0] is deduped[0]
        assert [c.dto.title for c in kept[1:]] == ["e0", "e1", "e2"]  # capped at 3
        assert telemetry.entity_kept == 3


# ------------------------------------------------------- semester twin dedup


class TestSemesterTwinDedup:
    """Twins of a repeated course collapse to the current instance."""

    NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)

    def _source(self, title, course="Patterns", ref=None, etype="lecture_unit"):
        source = _entity_source(title=title, etype=etype)
        source.course = CourseInfo(id=1, name=course)
        source.reference_date = ref
        return source

    def _at(self, year, month):
        return datetime(year, month, 1, tzinfo=timezone.utc)

    def test_released_twins_collapse_to_most_recent(self):
        old = self._source("Mediator (WS23/24)", "PSE (WS23/24)", self._at(2024, 9))
        cur = self._source("Mediator", "PSE", self._at(2026, 3))
        kept = dedupe_semester_twins([old, cur], "what is the mediator", now=self.NOW)
        assert kept == [cur]

    def test_future_twins_collapse_to_soonest(self):
        near = self._source("Mediator", "PSE", self._at(2027, 3))
        far = self._source("Mediator (WS27/28)", "PSE (WS27/28)", self._at(2028, 3))
        kept = dedupe_semester_twins([far, near], "mediator pattern", now=self.NOW)
        assert kept == [near]

    def test_released_beats_future(self):
        future = self._source("Mediator", "PSE", self._at(2027, 3))
        released = self._source("Mediator", "PSE", self._at(2026, 3))
        kept = dedupe_semester_twins([future, released], "mediator", now=self.NOW)
        assert kept == [released]

    def test_dated_query_keeps_all_twins(self):
        old = self._source("Mediator (WS23/24)", "PSE (WS23/24)", self._at(2024, 9))
        cur = self._source("Mediator", "PSE", self._at(2026, 3))
        kept = dedupe_semester_twins([old, cur], "mediator in WS23/24", now=self.NOW)
        assert kept == [old, cur]

    def test_distinct_courses_are_not_merged(self):
        a = self._source("W01 Introduction", "Deep Learning", self._at(2026, 3))
        b = self._source("W01 Introduction", "Patterns", self._at(2026, 3))
        assert len(dedupe_semester_twins([a, b], "introduction", now=self.NOW)) == 2

    def test_undatable_twins_keep_first_seen_order(self):
        first = self._source("Mediator", "PSE")
        second = self._source("Mediator", "PSE")
        kept = dedupe_semester_twins([first, second], "mediator", now=self.NOW)
        assert kept == [first]

    def test_render_parses_reference_date_as_utc(self):
        source = GlobalSearchPipeline._render_entity_sources(
            [_candidate_dto(startDate="2026-03-01T10:00:00")]
        )[0]
        assert source.reference_date == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- pipeline logic


class TestPipelineHelpers:
    """Pure pipeline helpers: labels, the Artemis clock line, rendering."""

    def test_source_label_for_entity_and_content(self):
        assert _source_label(_entity_source()) == "[Test course — Course information]"
        content = LectureSearchResultDTO(
            course=CourseInfo(id=1, name="C"),
            lecture=LectureInfo(id=2, name="L"),
            lectureUnit=LectureUnitInfo(
                id=3,
                name="U",
                link="/l",
                pageNumber=4,
                sourceType="lecture_unit_slide",
            ),
            snippet="s",
        )
        assert _source_label(content) == "[C — L, Slide 4]"

    def test_today_line_uses_the_artemis_clock(self):
        context = AccessContext(
            courseIds=[1], now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        )
        line = _today_line(context)
        assert "Sunday, 06 September 2026" in line
        assert "semesters or course copies" in line

    def test_render_entity_sources_builds_cards(self):
        sources = GlobalSearchPipeline._render_entity_sources(
            [
                _candidate_dto(courseId=11, courseName="Test course"),
                _candidate_dto(description="Full problem statement."),
            ]
        )
        assert not sources[0].via_pointer_tier and not sources[1].via_pointer_tier
        assert sources[0].course == CourseInfo(id=11, name="Test course")
        assert "RNN and LSTM Fundamentals" in sources[0].snippet
        assert sources[1].course is None
