import pytest
from pydantic import ValidationError

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO


def _base_payload(**overrides) -> dict:
    payload = {
        "authenticationToken": "tok",
        "artemisBaseUrl": "https://artemis.example",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("level", ["low", "moderate", "high"])
def test_support_level_accepts_valid_values(level):
    dto = PipelineExecutionSettingsDTO.model_validate(_base_payload(supportLevel=level))
    assert dto.support_level == level


def test_support_level_defaults_to_moderate_when_absent():
    dto = PipelineExecutionSettingsDTO.model_validate(_base_payload())
    assert dto.support_level == "moderate"


def test_support_level_rejects_unrecognised_value():
    with pytest.raises(ValidationError) as exc_info:
        PipelineExecutionSettingsDTO.model_validate(
            _base_payload(supportLevel="invalid_level")
        )
    assert any(err["loc"] == ("supportLevel",) for err in exc_info.value.errors())
