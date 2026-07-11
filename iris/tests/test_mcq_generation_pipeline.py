import json
import os
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableLambda

from iris.domain.status.activity_dto import ActivityState
from iris.pipeline.chat.mcq_chat_mixin import mcq_post_agent_hook, mcq_pre_agent_hook
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.pipeline.shared.mcq_generation_pipeline import (
    McqGenerationPipeline,
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
    jinja_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
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


def test_mcq_parallel_thread_reports_activity():
    emitted = []
    release_generation = threading.Event()
    generation_started = threading.Event()

    class FakeMcqPipeline:
        """Stub MCQ pipeline that signals generation start and blocks until released."""

        def __init__(self):
            self.tokens = []

        @staticmethod
        def run_in_thread(**kwargs):
            result_storage = kwargs["result_storage"]
            result_storage["queue"] = Queue()

            def generate():
                generation_started.set()
                release_generation.wait(2)
                result_storage["mcq_json"] = VALID_SINGLE_MCQ
                result_storage["queue"].put(("mcq", VALID_SINGLE_MCQ))
                result_storage["queue"].put(("done", None))

            thread = threading.Thread(target=generate)
            thread.start()
            return thread

    state = SimpleNamespace(
        mcq_parallel=True,
        mcq_count=1,
        dto=SimpleNamespace(user=SimpleNamespace(lang_key="en")),
        callback=MagicMock(),
        activity_tracker=ActivityTracker(
            lambda items, seq: emitted.append((seq, items))
        ),
        result="intro",
        allow_lecture_tool=False,
    )

    mcq_pre_agent_hook(
        state=state,
        mcq_pipeline=FakeMcqPipeline(),
        get_text_of_latest_user_message=lambda _state: "generate a question",
        db=MagicMock(),
        course_id=1,
        chat_history=[],
    )
    assert generation_started.wait(2)
    assert emitted[-1][1][0].name == "generate_mcq_questions"
    assert emitted[-1][1][0].state == ActivityState.RUNNING

    release_generation.set()
    mcq_post_agent_hook(
        state=state,
        mcq_pipeline=FakeMcqPipeline(),
        track_tokens=lambda _state, _token: None,
        timeout=2,
    )

    assert emitted[-1][1][0].state == ActivityState.FINISHED
    assert emitted[-1][1][0].duration_millis is not None
    assert VALID_SINGLE_MCQ in state.result


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
# run_in_thread tests
# ---------------------------------------------------------------------------


def test_run_in_thread_single_question():
    """run_in_thread with count=1 should store result and put it in queue."""
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    storage = {}
    thread = pipeline.run_in_thread(
        command="Generate a question about math",
        chat_history=None,
        user_language="en",
        result_storage=storage,
        count=1,
    )
    thread.join(timeout=10)

    # Should store in mcq_json for backward compat
    assert "mcq_json" in storage
    parsed = json.loads(storage["mcq_json"])
    assert parsed["type"] == "mcq"

    # Queue should have mcq + done
    q = storage["queue"]
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert any(t == "mcq" for t, _ in items)
    assert items[-1] == ("done", None)


def test_run_in_thread_error_on_failure():
    """run_in_thread should put error in queue on failure."""
    pipeline = _make_pipeline("not valid json")
    storage = {}
    thread = pipeline.run_in_thread(
        command="Generate a question",
        chat_history=None,
        user_language="en",
        result_storage=storage,
        count=1,
    )
    thread.join(timeout=10)

    assert "error" in storage
    q = storage["queue"]
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert any(t == "error" for t, _ in items)
    assert items[-1] == ("done", None)


def test_run_in_thread_multiple_questions():
    """run_in_thread with count>1 should generate multiple questions via queue."""
    pipeline = _make_pipeline(VALID_SINGLE_MCQ)
    storage = {}
    thread = pipeline.run_in_thread(
        command="Generate 3 questions about math",
        chat_history=None,
        user_language="en",
        result_storage=storage,
        count=3,
    )
    thread.join(timeout=30)

    q = storage["queue"]
    mcq_items = []
    while not q.empty():
        msg_type, data = q.get_nowait()
        if msg_type == "mcq":
            mcq_items.append(data)
        elif msg_type == "done":
            break
    assert len(mcq_items) == 3
    for item in mcq_items:
        parsed = json.loads(item)
        assert parsed["type"] == "mcq"
