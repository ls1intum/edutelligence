from iris.domain.struggle.struggle_intervention_pipeline_execution_dto import (
    StruggleInterventionPipelineExecutionDTO,
)


def test_execution_dto_carries_signal_and_settings():
    payload = {
        "settings": {
            "authenticationToken": "job-token-1",
            "artemisBaseUrl": "http://localhost:8080",
            "variant": "default",
        },
        "initialStages": [],
        "struggleSignal": {
            "alert": {
                "tSessionS": 540,
                "primaryBoundary": "FM",
                "boundaryTypes": ["FM"],
                "severity": 0.7,
                "path": "armed",
                "inWarmup": False,
                "inGrace": False,
            },
            "trajectory": [],
            "dominantComponents": [],
            "sessionSeconds": 540,
        },
        "chatHistory": [],
    }
    dto = StruggleInterventionPipelineExecutionDTO.model_validate(payload)
    assert dto.settings.authentication_token == "job-token-1"
    assert dto.struggle_signal.alert.primary_boundary == "FM"
