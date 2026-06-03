from unittest.mock import MagicMock

from iris.domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.web.status.ingestion_status_callback import IngestionStatusCallback


def test_error_code_defaults_to_none():
    dto = IngestionStatusUpdateDTO(stages=[], tokens=[])
    assert dto.error_code is None


def test_error_code_round_trips_through_snake_case_field_name():
    dto = IngestionStatusUpdateDTO(stages=[], tokens=[], error_code="YOUTUBE_PRIVATE")
    assert dto.error_code == "YOUTUBE_PRIVATE"


def test_error_code_accepts_wire_alias_error_code():
    # Pyris sends snake_case on the wire per spec; Jackson-side uses
    # @JsonProperty("error_code") on the Artemis DTO. Accept both on input.
    dto = IngestionStatusUpdateDTO(
        stages=[], tokens=[], **{"error_code": "YOUTUBE_LIVE"}
    )
    assert dto.error_code == "YOUTUBE_LIVE"


def test_error_code_serialized_under_snake_case_wire_key():
    dto = IngestionStatusUpdateDTO(stages=[], tokens=[], error_code="YOUTUBE_TOO_LONG")
    # Must dump with snake_case `error_code` to match Jackson contract.
    dumped = dto.model_dump(by_alias=True, exclude_none=True)
    assert dumped.get("error_code") == "YOUTUBE_TOO_LONG"
    assert "errorCode" not in dumped


def test_base_status_dto_does_not_carry_error_code():
    # error_code is scoped to ingestion only. Other pipelines must not see it
    # in their serialized payload (wire-contract narrowing).
    dto = StatusUpdateDTO(stages=[], tokens=[])
    dumped = dto.model_dump(by_alias=True)
    assert "error_code" not in dumped
    assert not hasattr(dto, "error_code")


def test_ingestion_callback_error_sets_error_code(monkeypatch):
    # Stub out HTTP delivery so the test doesn't hit the network
    monkeypatch.setattr(
        "iris.web.status.ingestion_status_callback.http_requests.post",
        MagicMock(return_value=MagicMock(status_code=200)),
    )
    cb = IngestionStatusCallback(
        run_id="test-run",
        base_url="http://localhost",
        include_transcription_stages=True,
    )
    cb.error("video is private", error_code="YOUTUBE_PRIVATE")
    assert cb.status.error_code == "YOUTUBE_PRIVATE"


def test_display_page_numbers_serialized_under_camel_case_wire_key():
    dto = IngestionStatusUpdateDTO(
        stages=[], tokens=[], display_page_numbers=[1, 2, -1]
    )
    dumped = dto.model_dump(by_alias=True, exclude_none=True)
    assert dumped.get("displayPageNumbers") == [1, 2, -1]
    assert "display_page_numbers" not in dumped


def test_ingestion_callback_done_sends_display_page_numbers_in_dedicated_field(
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
        include_transcription_stages=False,
    )
    cb.done("done", display_page_numbers=[3, 4, -1])

    payload = post_mock.call_args.kwargs["json"]
    assert payload["displayPageNumbers"] == [3, 4, -1]
    assert payload["result"] is None
    assert cb.status.display_page_numbers is None
