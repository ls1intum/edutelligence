from unittest.mock import MagicMock

from iris.domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum, StatusErrorDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.web.status.ingestion_status_callback import IngestionStatusCallback


def test_ingestion_error_code_serializes_inside_error_object():
    dto = IngestionStatusUpdateDTO(
        run_state=RunStateEnum.FAILED,
        error=StatusErrorDTO(message="video is private", code="YOUTUBE_PRIVATE"),
        tokens=[],
    )

    dumped = dto.model_dump(by_alias=True, exclude_none=True)

    assert dumped["error"] == {
        "message": "video is private",
        "code": "YOUTUBE_PRIVATE",
    }
    assert "error_code" not in dumped
    assert "errorCode" not in dumped


def test_base_status_dto_does_not_carry_error_code():
    dto = StatusUpdateDTO(run_state=RunStateEnum.RUNNING, tokens=[])
    dumped = dto.model_dump(by_alias=True)

    assert "error_code" not in dumped
    assert "errorCode" not in dumped
    assert not hasattr(dto, "error_code")


def test_ingestion_callback_fail_sends_error_code_in_error_object(monkeypatch):
    post_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(
        "iris.web.status.ingestion_status_callback.http_requests.post",
        post_mock,
    )
    cb = IngestionStatusCallback(
        run_id="test-run",
        base_url="http://localhost",
    )

    cb.fail("video is private", code="YOUTUBE_PRIVATE")

    payload = post_mock.call_args.kwargs["json"]
    assert payload["runState"] == "FAILED"
    assert payload["error"] == {
        "message": "video is private",
        "code": "YOUTUBE_PRIVATE",
    }


def test_display_page_numbers_serialized_under_camel_case_wire_key():
    dto = IngestionStatusUpdateDTO(
        run_state=RunStateEnum.FINISHED,
        tokens=[],
        display_page_numbers=[1, 2, -1],
    )

    dumped = dto.model_dump(by_alias=True, exclude_none=True)

    assert dumped.get("displayPageNumbers") == [1, 2, -1]
    assert "display_page_numbers" not in dumped


def test_ingestion_callback_finish_sends_display_page_numbers_in_dedicated_field(
    monkeypatch,
):
    post_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(
        "iris.web.status.ingestion_status_callback.http_requests.post",
        post_mock,
    )
    cb = IngestionStatusCallback(
        run_id="test-run",
        base_url="http://localhost",
    )

    cb.finish(display_page_numbers=[3, 4, -1])

    payload = post_mock.call_args.kwargs["json"]
    assert payload["runState"] == "FINISHED"
    assert payload["displayPageNumbers"] == [3, 4, -1]
    assert payload["result"] is None
