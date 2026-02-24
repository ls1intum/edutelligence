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


def test_format_recent_messages_limits_and_truncates():
    recent_messages = [f"Message {i}: " + "x" * 500 for i in range(12)]
    formatted = SessionTitleGenerationPipeline.format_recent_messages(recent_messages)

    lines = formatted.splitlines()
    assert len(lines) == SessionTitleGenerationPipeline.MAX_RECENT_MESSAGES
    assert lines[0].startswith("1. Message 2:")
    assert lines[-1].startswith("10. Message 11:")
    assert lines[0].endswith("...")
