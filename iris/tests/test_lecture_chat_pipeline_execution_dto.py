import pytest
from pydantic import ValidationError

from iris.domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)


def _base_payload() -> dict:
    return {
        "course": {"id": 1, "name": "Software Engineering"},
        "lecture": {"id": 42, "title": "Design Patterns", "units": []},
        "sessionTitle": "Questions",
        "chatHistory": [],
        "user": {"id": 123},
        "settings": None,
        "initialStages": [],
        "customInstructions": None,
    }


def test_accepts_optional_context_fields_when_valid():
    payload = _base_payload()
    payload["currentPdfPage"] = 5
    payload["currentVideoTimestamp"] = 150.5

    dto = LectureChatPipelineExecutionDTO.model_validate(payload)

    assert dto.current_pdf_page == 5
    assert dto.current_video_timestamp == 150.5


def test_accepts_when_context_fields_are_omitted():
    dto = LectureChatPipelineExecutionDTO.model_validate(_base_payload())

    assert dto.current_pdf_page is None
    assert dto.current_video_timestamp is None


def test_rejects_invalid_pdf_page():
    payload = _base_payload()
    payload["currentPdfPage"] = 0

    with pytest.raises(ValidationError):
        LectureChatPipelineExecutionDTO.model_validate(payload)


def test_rejects_invalid_video_timestamp():
    payload = _base_payload()
    payload["currentVideoTimestamp"] = -0.1

    with pytest.raises(ValidationError):
        LectureChatPipelineExecutionDTO.model_validate(payload)
