"""Tests for COMMAND marker messages in the chat history.

After a successful combined-view point-out, Artemis persists a marker message with sender COMMAND
and forwards it in the chat history of every subsequent pipeline run. The marker travels as the JSON
Artemis stored — the executed command in its ``{type, parameters}`` shape — and the wording the agent
reads is built here, so these tests cover both the conversion and the phrasing.
"""

# pylint: skip-file

from langchain_core.messages import SystemMessage

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


def test_point_out_marker_from_the_wire_becomes_a_system_note():
    """The full inbound path: the JSON shape Artemis sends -> the sentence the agent reads."""
    message = PyrisMessage.model_validate(
        {
            "sentAt": "2026-07-11T10:00:00Z",
            "sender": "COMMAND",
            "contents": [
                {
                    "type": "json",
                    "jsonContent": {
                        "type": "pointOut",
                        "parameters": {
                            "lectureUnitId": 42,
                            "lectureUnitName": "Intro",
                            "page": 3,
                            "displayPage": 5,
                        },
                    },
                }
            ],
        }
    )
    assert message.sender == IrisMessageRole.COMMAND
    assert isinstance(message.contents[0], JsonMessageContentDTO)

    result = convert_iris_message_to_langchain_message(message)

    assert isinstance(result, SystemMessage)
    # Named by the number printed on the slide, never by the point-out id it was navigated with.
    assert result.content == (
        "Earlier in this conversation, Iris pointed the student to the slide on "
        "page 5 of lecture unit 'Intro' (id 42) in the combined view."
    )


def test_marker_without_a_resolved_unit_name_describes_page_and_timestamp():
    marker = {
        "type": "pointOut",
        "parameters": {
            "lectureUnitId": 7,
            "page": 2,
            "displayPage": 4,
            "timestamp": 90.4,
        },
    }

    note = describe_command_marker(marker)

    assert "the slide on page 4 and the video at 90s of lecture unit 7" in note


def test_marker_names_no_page_when_the_printed_number_is_unknown():
    """Slides with no printed number — and markers stored before Artemis sent one — get no page.

    Falling back to the point-out id here would put an internal value the agent must never quote
    into the chat history for the rest of the conversation.
    """
    marker = {"type": "pointOut", "parameters": {"lectureUnitId": 7, "page": 2}}

    note = describe_command_marker(marker)

    assert "a slide of lecture unit 7" in note
    assert "point-out id" not in note


def test_marker_notes_never_carry_the_point_out_id():
    """The id is an internal navigation value; the chat history is where it would leak from.

    A note is re-read on every later turn, so an id in one is far more likely to end up quoted to
    the student than one in a single tool result.
    """
    notes = [
        describe_command_marker(
            {
                "type": "pointOut",
                "parameters": {"lectureUnitId": 7, "page": 11, "displayPage": 4},
            }
        ),
        describe_command_marker(
            {"type": "pointOut", "parameters": {"lectureUnitId": 7, "page": 11}}
        ),
        describe_command_marker(
            {
                "type": "pointOut",
                "parameters": {"lectureUnitId": 7, "page": 11, "timestamp": 90.4},
            }
        ),
    ]

    for note in notes:
        assert "11" not in note
        assert "point-out id" not in note


def test_unknown_marker_type_still_yields_a_usable_note():
    # A marker type this Pyris version does not know must never break a run over its wording.
    note = describe_command_marker({"type": "highlightTerm", "parameters": {}})

    assert "highlightTerm" in note


def test_malformed_marker_still_yields_a_usable_note():
    note = describe_command_marker({"type": "pointOut", "parameters": {"page": 3}})

    assert note == (
        "Earlier in this conversation, Iris pointed the student to a position in "
        "the combined view."
    )


def test_marker_notes_do_not_imply_the_spot_is_dealt_with():
    """A marker records a past point-out; it must not read as a reason to skip a fresh one.

    Wording like "already" pushes the agent into silently withholding a point-out that is still
    the right move, so it stays out of every branch — including the fallbacks.
    """
    notes = [
        describe_command_marker(
            {"type": "pointOut", "parameters": {"lectureUnitId": 7, "page": 2}}
        ),
        describe_command_marker({"type": "pointOut", "parameters": {"page": 3}}),
        describe_command_marker({"type": "highlightTerm", "parameters": {}}),
        describe_command_marker({"parameters": {}}),
    ]

    for note in notes:
        assert "already" not in note.lower()
