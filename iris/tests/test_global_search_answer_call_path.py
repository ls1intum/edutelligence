"""End-to-end coverage of GlobalSearchPipeline.__call__.

The rest of the global-search suite exercises the pipeline's helpers in
isolation, which left the orchestration in ``__call__`` itself untested: a
NameError on that path shipped past a fully green suite. These tests drive the
real ``__call__`` with the collaborators stubbed, so any name, signature or
ordering mistake between the retrieval, answer and fallback stages fails here.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import Mock

from iris.domain.search.global_search_dto import (
    CourseInfo,
    EntitySourceDTO,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline
from iris.domain.search.search_intent_dto import SearchIntent


def _content_source(snippet: str = "Signals are a reactive primitive.") -> LectureSearchResultDTO:
    return LectureSearchResultDTO(
        course=CourseInfo(id=42, name="Advanced Web Development"),
        lecture=LectureInfo(id=20, name="Angular Basics"),
        lectureUnit=LectureUnitInfo(
            id=30,
            name="Introduction to Signals",
            link="/courses/42/lectures/20/units/30",
            pageNumber=4,
            sourceType="lecture_unit_slide",
        ),
        snippet=snippet,
    )


def _pipeline(sources, raw_answer: str) -> GlobalSearchPipeline:
    """A pipeline whose retrieval and LLM stages are stubbed, leaving the real __call__."""
    pipeline = object.__new__(GlobalSearchPipeline)
    pipeline._render_entity_sources = Mock(return_value=[])
    pipeline._retrieve_sources = Mock(return_value=sources)
    pipeline._generate_answer = Mock(return_value=raw_answer)
    pipeline._append_tokens = Mock()
    pipeline.answer_llm = SimpleNamespace(tokens=SimpleNamespace())
    return pipeline


class TestAnswerCallPath:
    def test_grounded_content_answers_and_returns_the_used_source(self):
        pipeline = _pipeline([_content_source()], "Signals are reactive.[1]")

        result = pipeline(query="what are signals", intent=SearchIntent.TRIGGER_AI)

        assert result.answer is not None
        assert len(result.sources) == 1
        # The grounded path must not ask for the navigate prompt.
        assert pipeline._generate_answer.call_args.kwargs["navigate"] is False

    def test_pointer_only_context_switches_to_the_navigate_prompt(self):
        pointer = EntitySourceDTO(
            entityType="exercise",
            entityId=7,
            title="RNN and LSTM Fundamentals",
            course=CourseInfo(id=42, name="Advanced Web Development"),
            snippet="Quiz in Advanced Web Development",
            via_pointer_tier=True,
        )
        pipeline = _pipeline([pointer], '{"answer": "See the quiz.", "used_sources": [1]}')

        result = pipeline(query="is there an rnn quiz", intent=SearchIntent.TRIGGER_AI)

        assert result.answer is not None
        # Every grounded source came in below the floor, so this is navigation.
        assert pipeline._generate_answer.call_args.kwargs["navigate"] is True

    def test_streaming_handler_reaches_the_answer_stage(self):
        pipeline = _pipeline([_content_source()], "Signals are reactive.[1]")
        handler = Mock()

        pipeline(
            query="what are signals",
            intent=SearchIntent.TRIGGER_AI,
            stream_handler=handler,
        )

        assert pipeline._generate_answer.call_args.kwargs["stream_handler"] is handler

    def test_no_grounded_sources_returns_the_honest_empty_state(self):
        pipeline = _pipeline([_content_source(snippet="")], "unused")

        result = pipeline(query="what are signals", intent=SearchIntent.TRIGGER_AI)

        assert result.answer is None
        assert result.sources == []
        pipeline._generate_answer.assert_not_called()
