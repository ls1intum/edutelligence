"""Tests for COMMAND marker messages in the chat history.

After a successful combined-view point-out, Artemis persists a marker message with sender COMMAND
and forwards it in the chat history of every subsequent pipeline run. The marker travels as the JSON
Artemis stored — the executed command in its ``{type, parameters}`` shape — and the wording the agent
reads is built here, so these tests cover both the conversion and the phrasing.
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
from iris.domain.data.command_marker import describe_command_marker  # noqa: E402
from iris.domain.data.json_message_content_dto import (  # noqa: E402
    JsonMessageContentDTO,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.abstract_agent_pipeline import _filter_empty_messages  # noqa: E402

POINT_OUT_MARKER = {
    "type": "pointOut",
    "parameters": {"lectureUnitId": 42, "lectureUnitName": "Intro", "page": 3},
}


def _text_message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


def _command_message(marker: dict) -> PyrisMessage:
    return PyrisMessage(
        sender=IrisMessageRole.COMMAND,
        contents=[JsonMessageContentDTO(jsonContent=marker)],
    )


def test_command_message_validates_from_wire_format():
    message = PyrisMessage.model_validate(
        {
            "sentAt": "2026-07-11T10:00:00Z",
            "sender": "COMMAND",
            "contents": [{"type": "json", "jsonContent": POINT_OUT_MARKER}],
        }
    )
    assert message.sender == IrisMessageRole.COMMAND
    assert isinstance(message.contents[0], JsonMessageContentDTO)
    assert message.contents[0].json_content["type"] == "pointOut"


def test_point_out_marker_becomes_system_note():
    result = convert_iris_message_to_langchain_message(
        _command_message(POINT_OUT_MARKER)
    )

    assert isinstance(result, SystemMessage)
    assert result.content == (
        "Iris already pointed the student to index page 3 of lecture unit 'Intro' (id 42) "
        "in the combined view."
    )


def test_point_out_marker_without_a_resolved_unit_name_falls_back_to_the_id():
    marker = {"type": "pointOut", "parameters": {"lectureUnitId": 42, "page": 3}}

    note = describe_command_marker(marker)

    assert note == (
        "Iris already pointed the student to index page 3 of lecture unit 42 in the combined view."
    )


def test_point_out_marker_describes_page_and_timestamp_together():
    marker = {
        "type": "pointOut",
        "parameters": {"lectureUnitId": 7, "page": 2, "timestamp": 90.4},
    }

    note = describe_command_marker(marker)

    assert "index page 2 and the video at 90s of lecture unit 7" in note


def test_unknown_marker_type_still_yields_a_usable_note():
    # A marker type this Pyris version does not know must never break a run over its wording.
    note = describe_command_marker({"type": "highlightTerm", "parameters": {}})

    assert "highlightTerm" in note


def test_malformed_marker_still_yields_a_usable_note():
    note = describe_command_marker({"type": "pointOut", "parameters": {"page": 3}})

    assert (
        note == "Iris already pointed the student to a position in the combined view."
    )


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
    command = _command_message(POINT_OUT_MARKER)
    user = _text_message(IrisMessageRole.USER, "what is quicksort?")
    empty = _text_message(IrisMessageRole.ASSISTANT, "   ")

    filtered = _filter_empty_messages([command, user, empty])

    assert filtered == [command, user]
