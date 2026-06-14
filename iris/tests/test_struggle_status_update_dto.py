from iris.domain.status.struggle_intervention_status_update_dto import (
    StruggleInterventionStatusUpdateDTO,
)


def test_status_dto_serializes_action_fields_camelcase():
    dto = StruggleInterventionStatusUpdateDTO(stages=[])
    dto.action = "active"
    dto.confidence = 0.8
    dto.result = "Have you checked the empty-list case?"
    dto.rationale = "FM boundary, feedback-viewing dominant."
    dumped = dto.model_dump(by_alias=True)
    assert dumped["action"] == "active"
    assert dumped["confidence"] == 0.8
    assert dumped["result"] == "Have you checked the empty-list case?"
    assert dumped["rationale"] == "FM boundary, feedback-viewing dominant."
