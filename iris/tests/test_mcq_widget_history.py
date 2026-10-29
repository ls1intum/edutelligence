"""A quiz widget in the chat history is described as text and never fails the next message.

Artemis stores a generated multiple-choice question as JSON content of Iris' message and sends it
back in the history of every later run. A message that held nothing but the widget used to fail
the run of the student's next message.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.message_converters import (  # noqa: E402
    convert_iris_message_to_langchain_message,
    history_text,
)
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.image_message_content_dto import (  # noqa: E402
    ImageMessageContentDTO,
)
from iris.domain.data.json_message_content_dto import (  # noqa: E402
    JsonMessageContentDTO,
)
from iris.domain.data.mcq_widget import (  # noqa: E402
    MAX_DESCRIPTION_CHARS,
    describe_json_content,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.code_feedback_pipeline import (  # noqa: E402
    _chat_history_text,
)
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402

MCQ = {
    "type": "mcq",
    "question": "Which sorting algorithm is stable?",
    "options": [
        {"text": "Quicksort", "correct": False},
        {"text": "Merge sort", "correct": True},
        {"text": "Heap sort", "correct": False},
    ],
    "explanation": "Merge sort keeps equal elements in their original order.",
}
MCQ_SET = {
    "type": "mcq-set",
    "questions": [
        MCQ,
        {
            "question": "What is the worst case of insertion sort?",
            "options": [
                {"text": "O(n)", "correct": False},
                {"text": "O(n^2)", "correct": True},
            ],
            "explanation": "Every element moves past every other element.",
        },
    ],
}


def _message(sender, *contents) -> PyrisMessage:
    return PyrisMessage(sender=sender, contents=list(contents))


def _json(content: dict) -> JsonMessageContentDTO:
    return JsonMessageContentDTO(jsonContent=content)


def _text(text: str) -> TextMessageContentDTO:
    return TextMessageContentDTO(textContent=text)


def test_a_single_question_is_described_with_options_correct_answer_and_explanation():
    description = describe_json_content(MCQ)

    assert description.startswith("[Interactive quiz shown to the student")
    assert "Question: Which sorting algorithm is stable?" in description
    assert "A) Quicksort\nB) Merge sort\nC) Heap sort" in description
    assert "Correct answer: B" in description
    assert "Explanation: Merge sort keeps equal elements" in description


def test_a_question_set_numbers_its_questions():
    description = describe_json_content(MCQ_SET)

    assert "Question 1: Which sorting algorithm is stable?" in description
    assert "Question 2: What is the worst case of insertion sort?" in description
    assert "Correct answer: B" in description


@pytest.mark.parametrize(
    "content",
    [
        {"type": "mcq", "question": 5, "options": []},
        {"type": "mcq-set", "questions": [MCQ, "broken"]},
        {"type": "mcq-set", "questions": []},
        {"type": "something-else", "value": [1, 2]},
        ["not", "an", "object"],
        "a plain string",
    ],
)
def test_anything_that_is_not_a_valid_widget_is_kept_as_compact_text(content):
    description = describe_json_content(content)

    assert description.startswith("[Structured content] ")


def test_a_very_large_widget_is_clipped():
    huge = {"type": "something-else", "value": "x" * (MAX_DESCRIPTION_CHARS * 2)}

    assert len(describe_json_content(huge)) <= MAX_DESCRIPTION_CHARS + 10


def test_a_message_that_holds_only_a_widget_converts_to_an_assistant_message():
    message = _message(IrisMessageRole.ASSISTANT, _json(MCQ))

    converted = convert_iris_message_to_langchain_message(message)

    assert isinstance(converted, AIMessage)
    assert "Question: Which sorting algorithm is stable?" in converted.content


def test_a_message_with_text_and_widget_keeps_every_part_in_order():
    message = _message(
        IrisMessageRole.ASSISTANT,
        _text("Here is a question for you:"),
        _json(MCQ),
        _text("Let me know if you want another one."),
    )

    text = history_text(message)

    assert text.index("Here is a question") < text.index("Question: Which sorting")
    assert text.index("Question: Which sorting") < text.index("Let me know")


def test_a_plain_text_message_is_unchanged():
    message = _message(IrisMessageRole.USER, _text("  Why is B correct?\n"))

    converted = convert_iris_message_to_langchain_message(message)

    assert isinstance(converted, HumanMessage)
    assert converted.content == "  Why is B correct?\n"


def test_a_message_without_text_or_json_still_fails():
    message = _message(IrisMessageRole.USER, ImageMessageContentDTO(base64="aW1n"))

    with pytest.raises(ValueError, match="must be of type TextMessageContentDTO"):
        convert_iris_message_to_langchain_message(message)


def test_the_next_prompt_can_be_assembled_after_a_bare_widget():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    state = SimpleNamespace(
        message_history=[
            _message(IrisMessageRole.USER, _text("Quiz me on sorting")),
            _message(IrisMessageRole.ASSISTANT, _json(MCQ)),
            _message(IrisMessageRole.USER, _text("Why is B correct?")),
        ]
    )

    prompt = pipeline.assemble_prompt_with_history(state, system_prompt="Static")
    messages = prompt.format_messages(agent_scratchpad=[])

    assert [type(message) for message in messages[1:]] == [
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert "Merge sort" in messages[2].content
    assert messages[3].content == "Why is B correct?"


def test_the_code_feedback_history_describes_a_widget_instead_of_failing():
    history = [
        _message(IrisMessageRole.USER, _text("Quiz me on sorting")),
        _message(IrisMessageRole.ASSISTANT, _json(MCQ)),
        _message(IrisMessageRole.ASSISTANT, ImageMessageContentDTO(base64="aW1n")),
    ]

    text = _chat_history_text(history)

    assert "Quiz me on sorting" in text.splitlines()[0]
    assert "Merge sort" in text
