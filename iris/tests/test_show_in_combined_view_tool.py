"""Tests for the show-in-combined-view tool, its provider and the point-out command DTO."""

from types import SimpleNamespace

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.tools.chat_tool_providers import provide_show_in_combined_view
from iris.tools.show_in_combined_view import create_tool_show_in_combined_view


class _FakeCallback:
    """Records executed commands and returns a preconfigured result."""

    def __init__(self, applied=True, reason=None):
        self.result = CommandResultDTO(applied=applied, reason=reason)
        self.commands = []

    def in_progress(self, *args, **kwargs):
        pass

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

    assert "Nothing was shown" in result
    assert len(callback.commands) == 1


def test_tool_ignores_invalid_inputs():
    callback = _FakeCallback()
    tool = create_tool_show_in_combined_view(7, callback)
    result = tool(page=0, timestamp=-1.0)

    assert "No valid page or timestamp" in result
    assert not callback.commands


def test_provider_offered_when_combined_view_present():
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=9, page=2),
    )
    tool = provide_show_in_combined_view(_state([context]))
    assert tool is not None


def test_provider_not_offered_without_combined_view():
    standalone = VideoContextDTO(type="video", lectureUnitId=9, timestamp=1.0)
    assert provide_show_in_combined_view(_state([standalone])) is None
    assert provide_show_in_combined_view(_state([])) is None


def test_point_out_command_dto_serializes_with_camel_case():
    dto = PointOutCommandDTO(lecture_unit_id=9, page=2)
    dumped = dto.model_dump(by_alias=True)
    assert dumped["type"] == "pointOut"
    assert dumped["lectureUnitId"] == 9
    assert dumped["page"] == 2
    assert dumped["timestamp"] is None
