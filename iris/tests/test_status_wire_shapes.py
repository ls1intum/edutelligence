import importlib

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.status.activity_dto import ActivityDTO, ActivityKind, ActivityState
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum, StatusErrorDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO


def test_activity_dto_serializes_camel_case():
    dto = ActivityDTO(
        id="act-1",
        kind=ActivityKind.TOOL,
        name="lecture_content_retrieval",
        state=ActivityState.FINISHED,
        detail="sorting",
        result="12 sections",
        duration_millis=3100,
    )
    data = dto.model_dump(by_alias=True)
    assert data["durationMillis"] == 3100
    assert data["kind"] == "TOOL" and data["state"] == "FINISHED"


def test_activity_dto_optional_fields_default_none():
    dto = ActivityDTO(
        id="act-2",
        kind=ActivityKind.COMMAND,
        name="pointOut",
        state=ActivityState.RUNNING,
    )
    data = dto.model_dump(by_alias=True)
    assert data["detail"] is None
    assert data["result"] is None
    assert data["durationMillis"] is None


def test_run_state_and_error_shapes():
    assert RunStateEnum.RUNNING.value == "RUNNING"
    err = StatusErrorDTO(message="boom", code="YOUTUBE_PRIVATE")
    assert err.model_dump(by_alias=True) == {
        "message": "boom",
        "code": "YOUTUBE_PRIVATE",
    }


def test_chat_status_update_carries_run_state_and_activities():
    dto = ChatStatusUpdateDTO(
        run_state=RunStateEnum.RUNNING,
        activities=[],
        activity_seq=3,
    )
    data = dto.model_dump(by_alias=True)
    assert data["runState"] == "RUNNING"
    assert data["activitySeq"] == 3
    assert "stages" not in data


def test_status_updates_have_no_stages_field():
    assert "stages" not in set(StatusUpdateDTO.model_fields)


def test_stage_modules_are_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("iris.domain.status.stage_dto")
