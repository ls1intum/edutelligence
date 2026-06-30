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


def test_status_update_serializes_new_mode_fields_snake_case():
    dto = StruggleInterventionStatusUpdateDTO(
        stages=[],
        resolved=True,
        closing_sentence="Nice, that was the wrong index.",
        episode_label="Wrong index",
        ask=False,
        question=None,
    )
    dumped = dto.model_dump(by_alias=True)
    assert dumped["resolved"] is True
    assert dumped["closing_sentence"] == "Nice, that was the wrong index."
    assert dumped["episode_label"] == "Wrong index"
    assert dumped["ask"] is False
    assert "question" in dumped
