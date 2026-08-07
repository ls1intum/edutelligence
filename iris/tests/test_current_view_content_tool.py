"""Tests for the current-position content tool and its provider."""

from types import SimpleNamespace

from iris.tools.chat_tool_providers import provide_current_view_content
from iris.tools.current_view_content import create_tool_current_view_content


def test_tool_reads_out_all_position_blocks():
    """The tool hands back exactly the material the prompt deliberately leaves out."""
    tool = create_tool_current_view_content(
        [
            "The student is currently viewing page 3 ... The content of this slide:"
            "\n---\nPage 3 content\n---",
            "The student is currently at 50.0 seconds ... The transcript at this point:"
            "\n---\nTranscript 45-55\n---",
        ]
    )

    result = tool()

    assert "Page 3 content" in result
    assert "Transcript 45-55" in result


def test_tool_explains_itself_when_there_is_nothing_to_read():
    """An empty block list must not look like an empty slide."""
    result = create_tool_current_view_content([])()

    assert "not available" in result
    assert "retrieval" in result


def test_provider_offers_the_tool_when_a_position_has_material():
    state = SimpleNamespace(
        allow_lecture_tool=True, current_view_content_blocks=["page 3: content"]
    )

    tool = provide_current_view_content(state)

    assert tool is not None
    assert tool() == "page 3: content"


def test_provider_stays_silent_without_a_current_position():
    """No position, no tool — offering it would only invite bluffing about a slide."""
    assert (
        provide_current_view_content(SimpleNamespace(allow_lecture_tool=True)) is None
    )
    assert (
        provide_current_view_content(
            SimpleNamespace(allow_lecture_tool=True, current_view_content_blocks=[])
        )
        is None
    )


def test_provider_stays_silent_when_the_lecture_tool_is_not_allowed():
    """This tool hands out lecture material, so it is gated like every other lecture provider.

    The viewing context is filled in regardless of the variant, so without this guard a variant
    that may not retrieve lectures would still be handed the slide the student is looking at.
    """
    state = SimpleNamespace(
        allow_lecture_tool=False, current_view_content_blocks=["page 3: content"]
    )

    assert provide_current_view_content(state) is None
