"""Tests for the show-in-combined-view tool, its provider and the point-out command DTO."""

from types import SimpleNamespace

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.tools.chat_tool_providers import (
    CHAT_TOOL_PROVIDERS,
    provide_show_in_combined_view,
)
from iris.tools.show_in_combined_view import create_tool_show_in_combined_view


class _FakeCallback:
    """Records executed commands and returns a preconfigured result."""

    def __init__(self, applied=True, reason=None):
        self.result = CommandResultDTO(applied=applied, reason=reason)
        self.commands = []
        self.progress_messages = []

    def in_progress(self, *args, **kwargs):
        self.progress_messages.append((args, kwargs))

    def execute_command(self, command):
        self.commands.append(command)
        return self.result


def _state(lecture_contexts):
    return SimpleNamespace(
        lecture_contexts=lecture_contexts,
        callback=_FakeCallback(),
    )


def test_tool_executes_command_and_reports_success():
    callback = _FakeCallback(applied=True)
    tool = create_tool_show_in_combined_view(7, callback)
    result = tool(page=3, timestamp=42.0)

    assert "page 3" in result
    assert "Successfully showed" in result
    assert len(callback.commands) == 1
    command = callback.commands[0]
    assert command.type == "pointOut"
    assert command.lecture_unit_id == 7
    assert command.page == 3
    assert command.timestamp == 42.0


def test_tool_reports_when_not_applied():
    callback = _FakeCallback(applied=False, reason="combinedViewClosed")
    tool = create_tool_show_in_combined_view(7, callback)
    result = tool(page=3)

    assert result == ""
    assert len(callback.commands) == 1


def test_tool_ignores_invalid_inputs():
    callback = _FakeCallback()
    tool = create_tool_show_in_combined_view(7, callback)
    result = tool(page=0, timestamp=-1.0)

    assert result == ""
    assert not callback.commands


def test_provider_offered_when_combined_view_present():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
    )
    tool = provide_show_in_combined_view(_state([context]))
    assert tool is not None


def test_provider_passes_current_combined_view_position():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
        video=VideoContextDTO(type="video", lectureUnitId=9, timestamp=5.0),
    )
    state = _state([context])
    tool = provide_show_in_combined_view(state)

    result = tool(page=2, timestamp=5.0)

    assert "already at page 2 of the slides" in result
    assert "video at 5 seconds" in result
    assert (
        "most relevant lecture position for answering the student's question" in result
    )
    assert not state.callback.commands


def test_provider_omits_current_page_and_sends_only_new_timestamp():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
        video=VideoContextDTO(type="video", lectureUnitId=9, timestamp=5.0),
    )
    state = _state([context])
    tool = provide_show_in_combined_view(state)

    result = tool(page=2, timestamp=9.0)

    assert "Successfully showed" in result
    assert "video at 9 seconds" in result
    assert "page 2" not in result
    assert len(state.callback.commands) == 1
    command = state.callback.commands[0]
    assert command.page is None
    assert command.timestamp == 9.0


def test_provider_omits_current_timestamp_and_sends_only_new_page():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
        video=VideoContextDTO(type="video", lectureUnitId=9, timestamp=5.0),
    )
    state = _state([context])
    tool = provide_show_in_combined_view(state)

    result = tool(page=4, timestamp=5.0)

    assert "Successfully showed" in result
    assert "page 4 of the slides" in result
    assert "video at 5 seconds" not in result
    assert len(state.callback.commands) == 1
    command = state.callback.commands[0]
    assert command.page == 4
    assert command.timestamp is None


def test_provider_keeps_page_when_only_timestamp_is_covered_by_context():
    context = CombinedViewContextDTO(
        type="combinedView",
        video=VideoContextDTO(type="video", lectureUnitId=9, timestamp=5.0),
    )
    state = _state([context])
    tool = provide_show_in_combined_view(state)

    result = tool(page=4, timestamp=5.0)

    assert "Successfully showed" in result
    assert "page 4 of the slides" in result
    assert "video at 5 seconds" not in result
    assert len(state.callback.commands) == 1
    command = state.callback.commands[0]
    assert command.page == 4
    assert command.timestamp is None


def test_provider_keeps_timestamp_when_only_page_is_covered_by_context():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
    )
    state = _state([context])
    tool = provide_show_in_combined_view(state)

    result = tool(page=2, timestamp=9.0)

    assert "Successfully showed" in result
    assert "video at 9 seconds" in result
    assert "page 2" not in result
    assert len(state.callback.commands) == 1
    command = state.callback.commands[0]
    assert command.page is None
    assert command.timestamp == 9.0


def test_provider_not_offered_without_combined_view():
    standalone = VideoContextDTO(type="video", lectureUnitId=9, timestamp=1.0)
    assert provide_show_in_combined_view(_state([standalone])) is None
    assert provide_show_in_combined_view(_state([])) is None


def test_show_in_combined_view_is_not_offered_as_agent_tool():
    assert provide_show_in_combined_view not in CHAT_TOOL_PROVIDERS


def test_point_out_command_dto_serializes_with_camel_case():
    dto = PointOutCommandDTO(lecture_unit_id=9, page=2)
    dumped = dto.model_dump(by_alias=True)
    assert dumped["type"] == "pointOut"
    assert dumped["lectureUnitId"] == 9
    assert dumped["page"] == 2
    assert dumped["timestamp"] is None
