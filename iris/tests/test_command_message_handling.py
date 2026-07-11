"""Tests for COMMAND marker messages in the chat history.

After a successful combined-view point-out, Artemis persists a marker message with sender
COMMAND and a JSON content describing the point-out, and forwards it in the chat history of
every subsequent pipeline run. These tests cover that such messages validate, that the
langchain converter turns them into system notes the agent can use, and that the empty-message
filter keeps them while still dropping other json-bearing messages (e.g. MCQ artifacts).
"""

# pylint: skip-file

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# Bootstrap the iris package: importing iris.common directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.message_converters import (  # noqa: E402
    convert_iris_message_to_langchain_message,
)
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.json_message_content_dto import (  # noqa: E402
    JsonMessageContentDTO,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.pipeline.abstract_agent_pipeline import _filter_empty_messages  # noqa: E402


def _command_message(marker: dict) -> PyrisMessage:
    return PyrisMessage(
        sender=IrisMessageRole.COMMAND,
        contents=[JsonMessageContentDTO(jsonContent=json.dumps(marker))],
    )


def _text_message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


def test_command_message_validates_from_wire_format():
    message = PyrisMessage.model_validate(
        {
            "sentAt": "2026-07-11T10:00:00Z",
            "sender": "COMMAND",
            "contents": [
                {
                    "type": "json",
                    "jsonContent": '{"type": "pointOut", "lectureUnitId": 42, "page": 3}',
                }
            ],
        }
    )
    assert message.sender == IrisMessageRole.COMMAND
    assert isinstance(message.contents[0], JsonMessageContentDTO)
    assert message.contents[0].json_content["lectureUnitId"] == 42


def test_slide_point_out_becomes_system_note():
    message = _command_message(
        {
            "type": "pointOut",
            "lectureUnitId": 42,
            "lectureUnitName": "L07 Sorting",
            "page": 3,
        }
    )
    result = convert_iris_message_to_langchain_message(message)
    assert isinstance(result, SystemMessage)
    assert "page 3" in result.content
    assert "'L07 Sorting'" in result.content
    assert "id 42" in result.content
    assert "already pointed" in result.content


def test_video_point_out_becomes_system_note():
    message = _command_message(
        {"type": "pointOut", "lectureUnitId": 42, "timestamp": 125.0}
    )
    result = convert_iris_message_to_langchain_message(message)
    assert isinstance(result, SystemMessage)
    assert "video at 125s" in result.content
    assert "lecture unit 42" in result.content


def test_point_out_without_name_omits_quotes():
    message = _command_message({"type": "pointOut", "lectureUnitId": 7, "page": 1})
    result = convert_iris_message_to_langchain_message(message)
    assert isinstance(result, SystemMessage)
    assert "lecture unit 7" in result.content
    assert "'" not in result.content


def test_unexpected_marker_shape_falls_back_to_raw_json():
    marker = {"type": "somethingElse", "foo": "bar"}
    result = convert_iris_message_to_langchain_message(_command_message(marker))
    assert isinstance(result, SystemMessage)
    assert json.dumps(marker) in result.content


def test_point_out_without_position_falls_back_to_raw_json():
    marker = {"type": "pointOut", "lectureUnitId": 42}
    result = convert_iris_message_to_langchain_message(_command_message(marker))
    assert isinstance(result, SystemMessage)
    assert json.dumps(marker) in result.content


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


def test_non_command_json_message_still_raises():
    message = PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[JsonMessageContentDTO(jsonContent='{"mcq": true}')],
    )
    with pytest.raises(ValueError):
        convert_iris_message_to_langchain_message(message)


def test_filter_keeps_command_json_and_drops_llm_json():
    command = _command_message({"type": "pointOut", "lectureUnitId": 42, "page": 3})
    mcq_artifact = PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[JsonMessageContentDTO(jsonContent='{"questions": []}')],
    )
    user = _text_message(IrisMessageRole.USER, "what is quicksort?")
    empty = _text_message(IrisMessageRole.ASSISTANT, "   ")

    filtered = _filter_empty_messages([command, mcq_artifact, user, empty])

    assert filtered == [command, user]
