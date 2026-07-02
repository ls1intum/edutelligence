from iris.domain.struggle.struggle_intervention_pipeline_execution_dto import (
    StruggleInterventionPipelineExecutionDTO,
)


def _minimal_signal() -> dict:
    return {
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
    }


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


def test_execution_dto_parses_intent_and_episode_camelcase():
    payload = {
        "settings": None,
        "struggleSignal": _minimal_signal(),
        "intent": "stale_check",
        "episode": {
            "episodeId": "ep-1",
            "isNew": False,
            "hints": [
                {"level": "ambient", "text": "check the loop bound", "atSessionS": 42.0}
            ],
        },
    }
    dto = StruggleInterventionPipelineExecutionDTO.model_validate(payload)
    assert dto.intent == "stale_check"
    assert dto.episode.episode_id == "ep-1"
    assert dto.episode.is_new is False
    assert dto.episode.hints[0].level == "ambient"
    assert dto.episode.hints[0].at_session_s == 42.0


def test_execution_dto_intent_defaults_to_decide_when_absent():
    dto = StruggleInterventionPipelineExecutionDTO.model_validate(
        {"settings": None, "struggleSignal": _minimal_signal()}
    )
    assert dto.intent == "decide"
    assert dto.episode is None


def test_submission_carries_submitted_repository_camelcase():
    payload = {
        "settings": None,
        "struggleSignal": _minimal_signal(),
        "programmingExerciseSubmission": {
            "id": 7,
            "isPractice": False,
            "buildFailed": False,
            "repository": {"P.java": "new"},
            "submittedRepository": {"P.java": "old"},
        },
    }
    dto = StruggleInterventionPipelineExecutionDTO.model_validate(payload)
    assert dto.programming_exercise_submission.repository == {"P.java": "new"}
    assert dto.programming_exercise_submission.submitted_repository == {"P.java": "old"}


def test_submission_submitted_repository_defaults_empty_when_absent():
    payload = {
        "settings": None,
        "struggleSignal": _minimal_signal(),
        "programmingExerciseSubmission": {
            "id": 7,
            "isPractice": False,
            "buildFailed": False,
        },
    }
    dto = StruggleInterventionPipelineExecutionDTO.model_validate(payload)
    assert dto.programming_exercise_submission.submitted_repository == {}
