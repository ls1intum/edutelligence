"""Tests for COMMAND marker messages in the chat history.

After a successful combined-view point-out, Artemis persists a marker message with sender
COMMAND and forwards it in the chat history of every subsequent pipeline run. Artemis renders
the marker into a plain-text system note before sending it, so Pyris only ever sees text. These
tests cover that such messages validate and that the langchain converter turns them into system
notes the agent can use.
"""

# pylint: skip-file

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# Bootstrap the iris package: importing iris.common directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.message_converters import (  # noqa: E402
    convert_iris_message_to_langchain_message,
)
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.abstract_agent_pipeline import _filter_empty_messages  # noqa: E402


def _text_message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


def test_command_message_validates_from_wire_format():
    note = "Iris already pointed the student to page 3 of lecture unit 42 in the combined view."
    message = PyrisMessage.model_validate(
        {
            "sentAt": "2026-07-11T10:00:00Z",
            "sender": "COMMAND",
            "contents": [{"type": "text", "textContent": note}],
        }
    )
    assert message.sender == IrisMessageRole.COMMAND
    assert isinstance(message.contents[0], TextMessageContentDTO)
    assert message.contents[0].text_content == note


def test_command_message_becomes_system_note():
    note = "Iris already pointed the student to page 3 in the combined view."
    result = convert_iris_message_to_langchain_message(
        _text_message(IrisMessageRole.COMMAND, note)
    )
    assert isinstance(result, SystemMessage)
    assert result.content == note


def test_text_messages_convert_unchanged():
    user = convert_iris_message_to_langchain_message(
        _text_message(IrisMessageRole.USER, "hello")
    )
    assert isinstance(user, HumanMessage)
    assert user.content == "hello"

    assistant = convert_iris_message_to_langchain_message(
        _text_message(IrisMessageRole.ASSISTANT, "hi there")
    )
    assert isinstance(assistant, AIMessage)
    assert assistant.content == "hi there"


def test_filter_drops_blank_messages():
    command = _text_message(
        IrisMessageRole.COMMAND, "Iris already pointed the student to page 3."
    )
    user = _text_message(IrisMessageRole.USER, "what is quicksort?")
    empty = _text_message(IrisMessageRole.ASSISTANT, "   ")

    filtered = _filter_empty_messages([command, user, empty])

    assert filtered == [command, user]
