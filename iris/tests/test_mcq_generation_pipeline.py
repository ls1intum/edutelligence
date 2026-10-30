import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableLambda

from iris.pipeline.chat.mcq_chat_mixin import mcq_post_agent_hook
from iris.pipeline.prompts.environment import prompt_environment
from iris.pipeline.shared.mcq_generation_pipeline import (
    McqGenerationPipeline,
)
from iris.tools.mcq_generation import (
    MAX_QUESTIONS,
    create_tool_generate_mcq_questions,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

VALID_SINGLE_MCQ = json.dumps(
    {
        "type": "mcq",
        "question": "What is 2+2?",
        "options": [
            {"text": "3", "correct": False},
            {"text": "4", "correct": True},
            {"text": "5", "correct": False},
            {"text": "6", "correct": False},
        ],
        "explanation": "Basic arithmetic.",
    }
)

VALID_MCQ_SET = json.dumps(
    {
        "type": "mcq-set",
        "questions": [
            {
                "question": "Q1?",
                "options": [
                    {"text": "A", "correct": True},
                    {"text": "B", "correct": False},
                    {"text": "C", "correct": False},
                    {"text": "D", "correct": False},
                ],
                "explanation": "A is correct.",
            },
            {
                "question": "Q2?",
                "options": [
                    {"text": "X", "correct": False},
                    {"text": "Y", "correct": True},
                    {"text": "Z", "correct": False},
                    {"text": "W", "correct": False},
                ],
                "explanation": "Y is correct.",
            },
        ],
    }
)


def _make_pipeline(llm_return: str) -> McqGenerationPipeline:
    """Create an McqGenerationPipeline with a mocked LLM, bypassing __init__."""
    pipeline = McqGenerationPipeline.__new__(McqGenerationPipeline)
    pipeline.implementation_id = "mcq_generation_pipeline"
    pipeline.tokens = []

    template_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "iris",
        "pipeline",
        "prompts",
        "templates",
    )
    jinja_env = prompt_environment(template_dir)
    pipeline.prompt_template = jinja_env.get_template("mcq_generation_prompt.j2")
    pipeline.llm = SimpleNamespace(
        tokens=SimpleNamespace(pipeline=None),
    )
    pipeline.pipeline = RunnableLambda(lambda _: llm_return)
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_single_mcq_json_returned():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    result = pipeline(command="Generate a question about math")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"
    assert len(parsed["options"]) == 4


def test_valid_mcq_set_json_returned():
    pipeline = _make_pipeline(VALID_MCQ_SET)
    result = pipeline(command="Generate 2 questions")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq-set"
    assert len(parsed["questions"]) == 2


def test_markdown_fences_stripped():
    fenced = "```json\n" + VALID_SINGLE_MCQ + "\n```"
    pipeline = _make_pipeline(fenced)
    result = pipeline(command="Generate a question")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"


def test_invalid_json_raises():
    pipeline = _make_pipeline("This is not JSON at all")
    with pytest.raises(json.JSONDecodeError):
        pipeline(command="Generate a question")


def test_wrong_option_count_raises():
    bad_mcq = json.dumps(
        {
            "type": "mcq",
            "question": "Q?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": False},
                {"text": "C", "correct": False},
            ],
            "explanation": "Oops.",
        }
    )
    pipeline = _make_pipeline(bad_mcq)
    with pytest.raises(ValueError, match="exactly 4 options"):
        pipeline(command="Generate a question")


def test_multiple_correct_answers_raises():
    bad_mcq = json.dumps(
        {
            "type": "mcq",
            "question": "Q?",
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": True},
                {"text": "C", "correct": False},
                {"text": "D", "correct": False},
            ],
            "explanation": "Two correct.",
        }
    )
    pipeline = _make_pipeline(bad_mcq)
    with pytest.raises(ValueError, match="exactly 1 correct"):
        pipeline(command="Generate a question")


class _FakeToolPipeline:
    """Records how the MCQ tool calls the pipeline."""

    def __init__(self):
        self.tokens = []
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(("single", kwargs))
        return VALID_SINGLE_MCQ

    def generate_set(self, command, count, **kwargs):
        self.calls.append(("set", {"command": command, "count": count, **kwargs}))
        return VALID_MCQ_SET


def test_the_mcq_tool_generates_the_number_of_questions_the_agent_asks_for():
    pipeline = _FakeToolPipeline()
    storage = {}
    tool = create_tool_generate_mcq_questions(
        pipeline, [], MagicMock(), storage, language="German"
    )

    assert tool("Recursion") == "[MCQ_RESULT]"
    assert pipeline.calls[-1][0] == "single"
    assert storage["mcq_json"] == VALID_SINGLE_MCQ

    tool("Sorting", count=3)
    assert pipeline.calls[-1] == (
        "set",
        {
            "command": "Sorting",
            "count": 3,
            "chat_history": [],
            "language": "German",
            "lecture_content": None,
        },
    )
    assert storage["mcq_json"] == VALID_MCQ_SET

    tool("Graphs", count=50)
    assert pipeline.calls[-1][1]["count"] == MAX_QUESTIONS


def test_the_quiz_replaces_the_placeholder_and_its_usage_is_billed():
    pipeline = _FakeToolPipeline()
    pipeline.tokens = ["usage"]
    billed = []
    state = SimpleNamespace(
        result="Here is your quiz. [MCQ_RESULT]",
        mcq_result_storage={"mcq_json": VALID_SINGLE_MCQ},
    )

    mcq_post_agent_hook(
        state=state,
        mcq_pipeline=pipeline,
        track_tokens=lambda _state, token: billed.append(token),
    )

    assert state.result == "Here is your quiz. " + VALID_SINGLE_MCQ
    assert billed == ["usage"]
    assert not pipeline.tokens


def test_prompt_curly_braces_not_parsed_as_variables():
    """Regression test: the rendered prompt contains {"type": "mcq"...} JSON examples.
    These must NOT be interpreted as LangChain template variables."""
    captured_input = {}

    def capturing_llm(messages):
        captured_input["messages"] = messages
        return VALID_SINGLE_MCQ

    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    pipeline.pipeline = RunnableLambda(capturing_llm)

    # This should NOT raise KeyError about template variables
    result = pipeline(command="Generate a question about {curly} braces")
    parsed = json.loads(result)
    assert parsed["type"] == "mcq"

    # Verify the prompt was passed as a SystemMessage containing the JSON examples
    messages = captured_input["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert '"type":"mcq"' in messages[0].content


# ---------------------------------------------------------------------------
# generate_set tests
# ---------------------------------------------------------------------------


def test_generate_set_returns_one_mcq_set_with_the_requested_questions():
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)

    result = json.loads(pipeline.generate_set("Generate questions about math", 3))

    assert result["type"] == "mcq-set"
    assert len(result["questions"]) == 3


def test_generate_set_raises_when_no_question_could_be_generated():
    pipeline = _make_pipeline("not valid json")

    with pytest.raises(ValueError):
        pipeline.generate_set("Generate questions", 2)
