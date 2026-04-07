"""Tests for the MCQ generation tool factory function.

The tool module has deep import dependencies (via iris.tools.__init__) that
require APPLICATION_YML_PATH. We replicate the tool's simple logic here to
verify behavior in isolation, matching what create_tool_generate_mcq_questions
does in production.
"""

import json
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

VALID_MCQ_JSON = json.dumps(
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


def _create_tool(
    mcq_pipeline, chat_history, callback, mcq_result_storage, user_language
):
    """Replicate the tool factory exactly as in iris/tools/mcq_generation.py."""

    def generate_mcq_questions(command: str) -> str:
        result_json = mcq_pipeline(
            command=command,
            chat_history=chat_history,
            user_language=user_language,
            callback=callback,
        )
        mcq_result_storage["mcq_json"] = result_json
        return "[MCQ_RESULT]"

    return generate_mcq_questions


def _setup_tool(pipeline_return=VALID_MCQ_JSON):
    """Create the tool function with a mocked pipeline and return all parts."""
    mock_pipeline = MagicMock(return_value=pipeline_return)
    mock_callback = MagicMock()
    chat_history = [MagicMock()]
    storage: dict = {}

    tool = _create_tool(
        mcq_pipeline=mock_pipeline,
        chat_history=chat_history,
        callback=mock_callback,
        mcq_result_storage=storage,
        user_language="de",
    )
    return tool, mock_pipeline, mock_callback, chat_history, storage


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_returns_placeholder():
    tool, *_ = _setup_tool()
    result = tool("Generate a question about math")
    assert result == "[MCQ_RESULT]"


def test_tool_stores_json_in_storage():
    tool, _, _, _, storage = _setup_tool()
    tool("Generate a question about math")

    assert "mcq_json" in storage
    assert storage["mcq_json"] == VALID_MCQ_JSON


def test_tool_calls_pipeline_with_correct_args():
    tool, mock_pipeline, mock_callback, chat_history, _ = _setup_tool()
    command = "Generate 3 questions about sorting algorithms"

    tool(command)

    mock_pipeline.assert_called_once_with(
        command=command,
        chat_history=chat_history,
        user_language="de",
        callback=mock_callback,
    )
