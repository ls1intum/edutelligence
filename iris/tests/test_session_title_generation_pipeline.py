from types import SimpleNamespace

from jinja2 import Environment
from langchain_core.runnables import RunnableLambda

from iris.common.pipeline_enum import PipelineEnum
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)


def test_session_title_generation_handles_braces_in_recent_messages():
    pipeline = SessionTitleGenerationPipeline.__new__(SessionTitleGenerationPipeline)
    pipeline.prompt_template = Environment(autoescape=False).from_string(
        "Current: {{ current_session_title }}\n"
        "Messages: {{ recent_messages | safe }}\n"
        "Language: {{ user_language }}"
    )
    pipeline.pipeline = RunnableLambda(lambda _: "KEEP")
    pipeline.llm = SimpleNamespace(tokens=SimpleNamespace(pipeline=None))

    title_decision = pipeline(
        current_session_title="new chat",
        recent_messages=[
            'user: {"topic": "Vector DBs", "language": "en"}',
            "assistant: formatter edge case {foo!bar}",
            "assistant: nested braces {foo{bar}}",
        ],
    )

    assert title_decision == "KEEP"
    assert (
        pipeline.tokens.pipeline == PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
    )


def test_session_title_generation_retries_on_empty_output():
    pipeline = SessionTitleGenerationPipeline.__new__(SessionTitleGenerationPipeline)
    pipeline.prompt_template = Environment(autoescape=False).from_string(
        "Current: {{ current_session_title }}\n"
        "Messages: {{ recent_messages | safe }}\n"
        "Language: {{ user_language }}"
    )
    invoke_count = 0

    def generate_title(_):
        nonlocal invoke_count
        invoke_count += 1
        return "" if invoke_count == 1 else "UPDATE: Data Structures Overview"

    pipeline.pipeline = RunnableLambda(generate_title)
    pipeline.llm = SimpleNamespace(tokens=SimpleNamespace(pipeline=None))

    title_decision = pipeline(
        current_session_title="new chat",
        recent_messages=["user: explain stacks and queues"],
    )

    assert title_decision == "UPDATE: Data Structures Overview"
    assert invoke_count == 2
    assert (
        pipeline.tokens.pipeline == PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
    )
