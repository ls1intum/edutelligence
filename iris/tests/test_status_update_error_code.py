from unittest.mock import MagicMock

from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.web.status.ingestion_status_callback import IngestionStatusCallback


def test_error_code_defaults_to_none():
    dto = StatusUpdateDTO(stages=[], tokens=[])
    assert dto.error_code is None


def test_error_code_round_trips_through_snake_case_field_name():
    dto = StatusUpdateDTO(stages=[], tokens=[], error_code="YOUTUBE_PRIVATE")
    assert dto.error_code == "YOUTUBE_PRIVATE"


def test_error_code_accepts_wire_alias_error_code():
    # Pyris sends snake_case on the wire per spec; Jackson-side uses
    # @JsonProperty("error_code") on the Artemis DTO. Accept both on input.
    dto = StatusUpdateDTO(
        stages=[], tokens=[], **{"error_code": "YOUTUBE_LIVE"}
    )
    assert dto.error_code == "YOUTUBE_LIVE"


def test_error_code_serialized_under_snake_case_wire_key():
    dto = StatusUpdateDTO(
        stages=[], tokens=[], error_code="YOUTUBE_TOO_LONG"
    )
    # Must dump with snake_case `error_code` to match Jackson contract.
    dumped = dto.model_dump(by_alias=True, exclude_none=True)
    assert dumped.get("error_code") == "YOUTUBE_TOO_LONG"
    assert "errorCode" not in dumped


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
