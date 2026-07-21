# pylint: disable=protected-access,unused-import

import json
import math
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401 - establishes repo import order
from iris.llm import CompletionArguments
from iris.llm.external.openai_chat import (
    DirectOpenAIChatModel,
    QaProviderResponseError,
)
from iris.pipeline.abstract_agent_pipeline import AbstractAgentPipeline
from iris.pipeline.chat.interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline
from iris.pipeline.shared.mcq_generation_pipeline import McqGenerationPipeline
from iris.qa.cost import ModelRate
from iris.qa.loader import load_suite
from iris.qa.planning import (
    JUDGE_INPUT_CEILING,
    JUDGE_OUTPUT_CEILING,
    citation_call_allowance,
    guide_call_allowance,
    mcq_call_allowance,
    worker_token_ceiling,
)
from iris.qa.run import _ambiguous_worker_failure, worker_cost_reserve
from iris.qa.schema import UseCase
from iris.qa.worker import (
    _judge_activities,
    _judge_answer,
    _judge_evidence,
    _judge_policy_facts,
)

QA_ROOT = Path(__file__).parents[1] / "qa"


class _FakeLangchainModel:
    def __init__(self, *, request_handler, completion_args):
        del request_handler
        self.completion_args = completion_args

    def __or__(self, other):
        del other
        return Mock()


def _model(*, responses: bool) -> DirectOpenAIChatModel:
    return DirectOpenAIChatModel(  # type: ignore[call-arg]  # Pydantic private attr
        id="qa-model",
        type="openai_chat",
        model="gpt-test",
        api_key="test-key",  # pragma: allowlist secret
        use_responses_api=responses,
    )


def test_responses_request_uses_runner_cap(monkeypatch):
    monkeypatch.setenv("IRIS_QA_MAX_OUTPUT_TOKENS", "1500")
    params = _model(responses=True)._create_responses_params(
        [], CompletionArguments(max_tokens=4000), None
    )
    assert params["max_output_tokens"] == 1500


def test_chat_request_uses_runner_cap(monkeypatch):
    monkeypatch.setenv("IRIS_QA_MAX_OUTPUT_TOKENS", "1500")
    model = _model(responses=False)
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="ok", refusal=None, tool_calls=None),
            )
        ],
        usage=None,
    )
    model._client = client
    with patch(
        "iris.llm.external.openai_chat.convert_to_iris_message", return_value=Mock()
    ):
        model.chat([], CompletionArguments(max_tokens=4000), None)
    assert (
        client.chat.completions.create.call_args.kwargs["max_completion_tokens"] == 1500
    )


def test_judge_transport_bounds_verbose_answers_and_preserves_both_ends():
    response = "HEAD" + "x" * 4_000 + "TAIL"

    excerpt, metadata = _judge_answer(response)

    assert excerpt is not None
    assert excerpt.startswith("HEAD")
    assert excerpt.endswith("TAIL")
    assert "middle omitted by QA transport" in excerpt
    assert len(excerpt) < len(response)
    assert metadata == {
        "originalCharacters": len(response),
        "originalWords": 1,
        "truncatedForJudge": True,
    }


def test_incomplete_responses_fail_closed(monkeypatch):
    monkeypatch.setenv("IRIS_QA_FAIL_ON_TRUNCATION", "1")
    model = _model(responses=True)
    model._client = Mock()
    model._client.responses.create.return_value = SimpleNamespace(
        status="incomplete", incomplete_details={"reason": "max_output_tokens"}
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        model.chat([], CompletionArguments(), None)


def test_streamed_failed_response_preserves_billable_usage(monkeypatch):
    monkeypatch.setenv("IRIS_QA_PROVIDER_USAGE_LOG", "/unused/qa-usage.jsonl")
    model = _model(responses=True)
    failed_response = SimpleNamespace(
        status="failed",
        error={"code": "server_error"},
        usage=SimpleNamespace(input_tokens=321, output_tokens=45),
    )
    model._client = Mock()
    model._client.responses.create.return_value = [
        SimpleNamespace(type="response.failed", response=failed_response)
    ]

    with pytest.raises(QaProviderResponseError, match="completion failed") as raised:
        model.chat(
            [],
            CompletionArguments(stream_handler=Mock()),
            None,
        )

    assert raised.value.qa_token_usage.num_input_tokens == 321
    assert raised.value.qa_token_usage.num_output_tokens == 45


def test_agent_executor_uses_runner_turn_cap(monkeypatch):
    monkeypatch.setenv("IRIS_QA_MAX_AGENT_TURNS", "4")
    fake_agent = Mock()
    with patch(
        "iris.pipeline.abstract_agent_pipeline.create_tool_calling_agent",
        return_value=fake_agent,
    ), patch("iris.pipeline.abstract_agent_pipeline.AgentExecutor") as executor:
        AbstractAgentPipeline._create_agent_executor(
            Mock(), llm=Mock(), prompt=Mock(), tool_functions=[]
        )
    assert executor.call_args.kwargs["max_iterations"] == 4
    assert executor.call_args.kwargs["early_stopping_method"] == "force"


def test_qa_auxiliary_output_caps_match_the_cost_plan(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    with (
        patch(
            "iris.pipeline.chat.interaction_suggestion_pipeline.resolve_model",
            return_value="qa-mini",
        ),
        patch("iris.pipeline.chat.interaction_suggestion_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.chat.interaction_suggestion_pipeline.IrisLangchainChatModel",
            _FakeLangchainModel,
        ),
    ):
        suggestions = InteractionSuggestionPipeline()
    with (
        patch(
            "iris.pipeline.shared.citation_pipeline.resolve_model",
            return_value="qa-mini",
        ),
        patch("iris.pipeline.shared.citation_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.shared.citation_pipeline.IrisLangchainChatModel",
            _FakeLangchainModel,
        ),
    ):
        citations = CitationPipeline()
    with (
        patch(
            "iris.pipeline.shared.mcq_generation_pipeline.resolve_model",
            return_value="qa-mini",
        ),
        patch("iris.pipeline.shared.mcq_generation_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.shared.mcq_generation_pipeline.IrisLangchainChatModel",
            _FakeLangchainModel,
        ),
    ):
        mcqs = McqGenerationPipeline()

    assert suggestions.llm.completion_args.max_tokens == 300
    assert citations.llms["default"].completion_args.max_tokens == 1000
    assert citations.llms["advanced"].completion_args.max_tokens == 1000
    assert citations._keyword_summary_completion_args.max_tokens == 1000
    assert mcqs.llm.completion_args.max_tokens == 2000
    assert mcqs.llm.completion_args.temperature == 0.2
    assert mcqs.llm.completion_args.response_format == "JSON"


def test_auxiliary_output_caps_do_not_change_normal_production(monkeypatch):
    monkeypatch.delenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", raising=False)
    with (
        patch(
            "iris.pipeline.chat.interaction_suggestion_pipeline.resolve_model",
            return_value="qa-mini",
        ),
        patch("iris.pipeline.chat.interaction_suggestion_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.chat.interaction_suggestion_pipeline.IrisLangchainChatModel",
            _FakeLangchainModel,
        ),
    ):
        suggestions = InteractionSuggestionPipeline()
    with (
        patch(
            "iris.pipeline.shared.citation_pipeline.resolve_model",
            return_value="qa-mini",
        ),
        patch("iris.pipeline.shared.citation_pipeline.LlmRequestHandler"),
        patch(
            "iris.pipeline.shared.citation_pipeline.IrisLangchainChatModel",
            _FakeLangchainModel,
        ),
    ):
        citations = CitationPipeline()

    assert suggestions.llm.completion_args.max_tokens is None
    assert citations.llms["default"].completion_args.max_tokens is None
    assert citations._keyword_summary_completion_args.max_tokens is None


def test_worker_reserve_covers_complete_cap_one_overrun_call_and_max_rate():
    scenario = SimpleNamespace(
        mode="PROGRAMMING_EXERCISE_CHAT",
        use_case=UseCase.CHAT,
        expectations=SimpleNamespace(require_citation=False, require_mcq=None),
        token_ceiling=SimpleNamespace(
            max_input_tokens=60_000,
            max_output_tokens=6_000,
            max_output_tokens_per_call=1_500,
        ),
    )
    mini = ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.50"))
    large = ModelRate("gpt-5.5", Decimal("5.00"), Decimal("30.00"))
    judge = ModelRate("gpt-5.4", Decimal("2.50"), Decimal("15.00"))
    rate_card = SimpleNamespace(candidates=(mini, large), judge=judge, auxiliary=mini)

    assert worker_cost_reserve(scenario, rate_card) == Decimal("1.0255")


def test_missing_provider_usage_is_treated_as_an_ambiguous_charge():
    completed = SimpleNamespace(returncode=1)
    result = {
        "executionError": (
            "RuntimeError: Production callback failed "
            "(RuntimeError: QA provider response omitted token usage)"
        )
    }

    assert _ambiguous_worker_failure(completed, result)


def test_retryable_api_status_without_usage_is_treated_as_ambiguous():
    completed = SimpleNamespace(returncode=1)
    result = {
        "executionError": (
            "RuntimeError: Production callback failed "
            "(APIStatusError: request timed out)"
        )
    }

    assert _ambiguous_worker_failure(completed, result)


def test_worker_reserve_covers_every_parallel_mcq_response():
    scenario = SimpleNamespace(
        mode="COURSE_CHAT",
        use_case=UseCase.CHAT,
        expectations=SimpleNamespace(
            require_citation=False, require_mcq="set", mcq_count=3
        ),
        token_ceiling=SimpleNamespace(
            max_input_tokens=36_000,
            max_output_tokens=4_500,
            max_output_tokens_per_call=1_500,
        ),
    )
    mini = ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.50"))
    large = ModelRate("gpt-5.5", Decimal("5.00"), Decimal("30.00"))
    judge = ModelRate("gpt-5.4", Decimal("2.50"), Decimal("15.00"))
    rate_card = SimpleNamespace(candidates=(mini, large), judge=judge, auxiliary=mini)

    assert worker_cost_reserve(scenario, rate_card) == Decimal("1.5005")


def test_mcq_allowance_covers_subtopic_call_and_parallel_question_fanout():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    single = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "course-one-mcq-moderate"
    )
    multiple = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "course-three-mcqs-german-high"
    )

    assert mcq_call_allowance(single) == (2, 1)
    assert mcq_call_allowance(multiple) == (7, 3)


def test_low_support_guide_allowance_covers_all_chat_modes_but_not_mcqs():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    lecture = next(s for s in suite.scenarios if s.id == "lecture-german-missing-low")
    programming = next(s for s in suite.scenarios if s.id == "prog-compile-low")
    mcq = next(s for s in suite.scenarios if s.id == "course-one-mcq-moderate")

    assert guide_call_allowance(lecture) == 1
    assert guide_call_allowance(programming) == 1
    assert guide_call_allowance(mcq) == 0
    assert worker_token_ceiling(lecture) == (
        lecture.token_ceiling.max_input_tokens + JUDGE_INPUT_CEILING + 10_000,
        lecture.token_ceiling.max_output_tokens + JUDGE_OUTPUT_CEILING + 2_200,
    )


def test_citation_allowance_covers_formatter_and_per_source_fanout():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    combined = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "lecture-combined-high"
    )

    # Three controlled lecture items: one formatter, three keyword calls, and
    # three summary calls; summaries can run beside one keyword worker.
    assert citation_call_allowance(combined) == (7, 4)


def test_qa_mcq_failure_does_not_launch_fallback_calls(monkeypatch):
    monkeypatch.setenv("IRIS_QA_DISABLE_PIPELINE_RETRIES", "1")
    pipeline = object.__new__(McqGenerationPipeline)
    with patch.object(
        McqGenerationPipeline,
        "_extract_subtopics",
        side_effect=RuntimeError("provider failed"),
    ), patch.object(
        McqGenerationPipeline, "_generate_multiple_sequential"
    ) as fallback, pytest.raises(
        RuntimeError, match="fallback calls are disabled"
    ):
        pipeline._generate_multiple(
            "three questions",
            chat_history=[],
            user_language="en",
            count=3,
            q=Mock(),
        )

    fallback.assert_not_called()


def test_checked_in_judge_evidence_stays_within_the_priced_input_cap():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )

    for scenario in suite.scenarios:
        answer, answer_metadata = _judge_answer(
            " ".join(["explanation"] * scenario.expectations.max_words)
        )
        request = {
            "rubric": [item.model_dump() for item in scenario.expectations.rubric],
            # Exercise every scenario at its configured prose limit with a
            # deliberately long ordinary word, not merely with an empty answer.
            "answer": answer,
            "answerMetadata": answer_metadata,
            "activities": _judge_activities(
                [
                    {"name": name, "state": "FINISHED"}
                    for name in (
                        scenario.expectations.required_tools
                        + scenario.expectations.optional_tools
                    )
                ]
            ),
            "evidence": _judge_evidence(scenario),
            "policyFacts": _judge_policy_facts(scenario),
        }
        estimate = math.ceil(len(json.dumps(request, default=str)) / 3) + 200
        assert estimate <= JUDGE_INPUT_CEILING, (
            scenario.id,
            estimate,
            JUDGE_INPUT_CEILING,
        )


def test_judge_evidence_includes_production_derived_competency_mastery():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item for item in suite.scenarios if item.id == "course-study-plan-high"
    )

    evidence = _judge_evidence(scenario)
    competencies = evidence["metrics"]["competencies"]

    assert evidence["useCase"] == "chat"
    assert evidence["chatMode"] == "COURSE_CHAT"
    assert [
        (item["title"], item["mastery"], item["masteryThreshold"])
        for item in competencies
    ] == [
        ("Sorting Algorithms", 36, 80),
        ("Graph Traversal", 11, 80),
    ]


def test_judge_evidence_includes_only_bounded_lecture_dto_facts():
    suite = load_suite(
        QA_ROOT / "scenarios",
        QA_ROOT / "fixtures",
        QA_ROOT / "artifacts",
    )
    scenario = next(
        item
        for item in suite.scenarios
        if item.mode == "LECTURE_CHAT"
        and item.support_level == "low"
        and "Quanten-Sortieralgorithmen" in str(item.payload.get("chatHistory"))
    )

    evidence = _judge_evidence(scenario)

    assert evidence["lectureFacts"] == {
        "id": 6001,
        "title": "Divide and Conquer",
        "description": "Recurrences, merge sort, and asymptotic analysis.",
    }

    scenario.payload["lecture"] = {
        "id": 6001,
        "title": "T" * 300,
        "description": "D" * 1_000,
        "startDate": "not evaluator evidence",
    }
    bounded = _judge_evidence(scenario)["lectureFacts"]
    assert set(bounded) == {"id", "title", "description"}
    assert len(bounded["title"]) == 160
    assert len(bounded["description"]) == 500


def test_judge_policy_facts_are_scoped_to_production_request_contexts():
    def scenario(
        *,
        use_case="chat",
        mode="COURSE_CHAT",
        support_level="moderate",
        require_mcq=None,
        query="What should I notice about my dashboard?",
    ):
        return SimpleNamespace(
            use_case=use_case,
            mode=mode,
            support_level=support_level,
            payload={
                "chatHistory": [
                    {
                        "sender": "USER",
                        "contents": [{"textContent": query}],
                    }
                ]
            },
            expectations=SimpleNamespace(
                require_mcq=require_mcq,
            ),
        )

    planning = _judge_policy_facts(scenario())
    assert set(planning) == {"nearSoftDueDateAttentionRule"}
    assert (
        "course progress or planning request"
        in planning["nearSoftDueDateAttentionRule"]
    )
    assert "four or fewer days" in planning["nearSoftDueDateAttentionRule"]
    assert "below 70%" in planning["nearSoftDueDateAttentionRule"]

    low_lecture = _judge_policy_facts(
        scenario(mode="LECTURE_CHAT", support_level="low")
    )
    assert set(low_lecture) == {
        "lowSupportTaskSpecificRule",
        "lowSupportExceptions",
    }

    low_course_faq = _judge_policy_facts(
        scenario(
            support_level="low",
            query=(
                "When exactly is insertion sort due, and does the grace period "
                "apply?"
            ),
        )
    )
    assert set(low_course_faq) == {"lowSupportOfficialLogisticsException"}
    assert (
        "production request evidence plan"
        in low_course_faq["lowSupportOfficialLogisticsException"]
    )
    assert (
        "concise authoritative fact"
        in low_course_faq["lowSupportOfficialLogisticsException"]
    )
    assert (
        "turning the request into a quiz"
        in low_course_faq["lowSupportOfficialLogisticsException"]
    )

    low_pedagogical_queries = [
        scenario(
            support_level="low",
            query="Explain the definition of a stable sorting algorithm.",
        ),
        scenario(
            mode="PROGRAMMING_EXERCISE_CHAT",
            support_level="low",
            query="Help me understand the loop invariant.",
        ),
        scenario(
            mode="LECTURE_CHAT",
            support_level="low",
            query="What does the recurrence on this slide tell me?",
        ),
        # A keyword mention alone is not official-logistics request intent.
        scenario(
            support_level="low",
            query="I noted the deadline in my calendar.",
        ),
        # Scenario expectations do not override production request detection.
        scenario(
            support_level="low",
            require_mcq="set",
            query="Explain the definition of a stable sorting algorithm.",
        ),
    ]
    assert all(
        set(_judge_policy_facts(item))
        == {"lowSupportTaskSpecificRule", "lowSupportExceptions"}
        for item in low_pedagogical_queries
    )

    actual_mcq = scenario(
        support_level="low",
        query="Please make two quiz questions about stable sorting.",
    )
    assert not _judge_policy_facts(actual_mcq)

    unrelated_contexts = [
        scenario(mode="LECTURE_CHAT", support_level="moderate"),
        scenario(
            use_case="tutor_suggestion",
            mode=None,
            support_level="low",
        ),
        scenario(
            mode="COURSE_CHAT",
            support_level="high",
            query="Explain the definition of a stable sorting algorithm.",
        ),
    ]
    assert all(not _judge_policy_facts(item) for item in unrelated_contexts)
