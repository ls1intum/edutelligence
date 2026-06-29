"""Tests for the show-in-combined-view tool, its provider and the point-out action DTO."""

from types import SimpleNamespace

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.status.point_out_action_dto import PointOutActionDTO
from iris.tools.chat_tool_providers import provide_show_in_combined_view
from iris.tools.show_in_combined_view import create_tool_show_in_combined_view


def _state(lecture_contexts):
    return SimpleNamespace(
        lecture_contexts=lecture_contexts,
        callback=SimpleNamespace(in_progress=lambda *a, **k: None),
    )


def test_tool_records_page_and_timestamp():
    storage = {}
    tool = create_tool_show_in_combined_view(
        7, SimpleNamespace(in_progress=lambda *a, **k: None), storage
    )
    result = tool(page=3, timestamp=42.0, reason="Binary search")
    assert "page 3" in result
    assert storage["action"] == {
        "lecture_unit_id": 7,
        "page": 3,
        "timestamp": 42.0,
        "reason": "Binary search",
    }


def test_tool_ignores_invalid_inputs():
    storage = {}
    tool = create_tool_show_in_combined_view(
        7, SimpleNamespace(in_progress=lambda *a, **k: None), storage
    )
    result = tool(page=0, timestamp=-1.0)
    assert "action" not in storage
    assert "No valid page or timestamp" in result


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


def test_point_out_action_dto_serializes_with_camel_case():
    dto = PointOutActionDTO(lecture_unit_id=9, page=2, reason="x")
    dumped = dto.model_dump(by_alias=True)
    assert dumped["lectureUnitId"] == 9
    assert dumped["page"] == 2
    assert dumped["timestamp"] is None
