"""A quiz widget in the chat history is described as text and never fails the next message.

Artemis stores a generated multiple-choice question as JSON content of Iris' message and sends it
back in the history of every later run. The answers a student gives are stored in the same JSON.
"""

from langchain_core.messages import HumanMessage

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.message_converters import (  # noqa: E402
    convert_iris_message_to_langchain_message,
    describe_json_content,
    normalize_history_message,
)
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.image_message_content_dto import (  # noqa: E402
    ImageMessageContentDTO,
)
from iris.domain.data.json_message_content_dto import (  # noqa: E402
    JsonMessageContentDTO,
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


def _message(sender, *contents) -> PyrisMessage:
    return PyrisMessage(sender=sender, contents=list(contents))


def _json(content) -> JsonMessageContentDTO:
    return JsonMessageContentDTO(jsonContent=content)


def _text(text: str) -> TextMessageContentDTO:
    return TextMessageContentDTO(textContent=text)


def test_a_single_question_lists_options_correct_answer_and_explanation():
    description = describe_json_content(MCQ)

    assert "Quiz question shown to the student: Which sorting algorithm" in description
    assert "  2) Merge sort (correct)" in description
    assert "Explanation: Merge sort keeps equal elements" in description
    assert "The student has not answered it yet." in description


def test_non_object_json_is_kept_as_clipped_text():
    assert describe_json_content(["x" * 5000]).startswith('["xxx')
    assert len(describe_json_content(["x" * 5000])) == 2000


def test_a_message_with_text_and_widget_keeps_every_part_in_order():
    message = _message(
        IrisMessageRole.ASSISTANT,
        _text("Here is a question for you:"),
        _json(MCQ),
        _text("Let me know if you want another one."),
    )

    text = normalize_history_message(message).contents[0].text_content

    assert text.index("Here is a question") < text.index("Which sorting")
    assert text.index("Which sorting") < text.index("Let me know")


def test_a_plain_text_message_is_unchanged():
    message = _message(IrisMessageRole.USER, _text("  Why is B correct?\n"))

    converted = convert_iris_message_to_langchain_message(message)

    assert isinstance(converted, HumanMessage)
    assert converted.content == "  Why is B correct?\n"


def test_the_chat_agent_reads_a_bare_widget_in_its_history():
    # The history step needs no models, so the pipeline is built without its LLM setup.
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    message = _message(IrisMessageRole.ASSISTANT, _json(MCQ))

    history_message = pipeline._history_message(  # pylint: disable=protected-access
        message
    )

    assert history_message.sender == IrisMessageRole.ASSISTANT
    assert "2) Merge sort (correct)" in history_message.contents[0].text_content


def test_the_code_feedback_history_describes_a_widget_instead_of_failing():
    history = [
        _message(IrisMessageRole.USER, _text("Quiz me on sorting")),
        _message(IrisMessageRole.ASSISTANT, _json(MCQ)),
        _message(IrisMessageRole.ASSISTANT, ImageMessageContentDTO(base64="aW1n")),
    ]

    lines = _chat_history_text(history).splitlines()

    assert "Quiz me on sorting" in lines[0]
    assert any("Merge sort (correct)" in line for line in lines)
    assert not any("aW1n" in line for line in lines)
