"""Translates a test case into the chat request Artemis sends to Pyris (ChatPipelineExecutionDTO).

Pyris expects data the test cases do not contain (user, course, IDs). These get fixed
placeholder values that are the same for every test case.
"""

from typing import Any

from ..evaluation_pipeline.models import ChatMode, TestCase

PLACEHOLDER_USER_ID = 1
PLACEHOLDER_COURSE = {"id": 1, "name": "Benchmark course"}

SENDER = {"student": "USER", "iris": "LLM"}


def build_chat_request(
    test_case: TestCase,
    *,
    callback_base_url: str,
    run_id: str,
    callback_token: str,
    variant: str = "default",
    support_level: str = "moderate",
    selection: str = "CLOUD_AI",
) -> dict[str, Any]:
    """Returns the JSON body for POST /api/v1/pipelines/chat/run."""
    request: dict[str, Any] = {
        "settings": {
            "authenticationToken": callback_token,
            "runId": run_id,
            "artemisBaseUrl": callback_base_url,
            "variant": variant,
            "supportLevel": support_level,
            "selection": selection,
        },
        "chatMode": test_case.chat_mode.value,
        "user": {"id": PLACEHOLDER_USER_ID},
        "course": PLACEHOLDER_COURSE,
        # the last message is the student message Iris has to answer
        "chatHistory": [
            {"sender": SENDER[m.sender], "contents": [{"textContent": m.text}]}
            for m in test_case.conversation
        ],
    }

    if test_case.chat_mode == ChatMode.PROGRAMMING_EXERCISE and test_case.exercise:
        request["programmingExercise"] = {
            "id": test_case.id,
            "title": test_case.exercise.title,
            "problemStatement": test_case.exercise.problem_statement,
            "programmingLanguage": test_case.exercise.programming_language,
        }
        if test_case.submission:
            request["programmingExerciseSubmission"] = {
                "id": test_case.id,
                "repository": test_case.submission.repository,
                "isPractice": False,
                "buildFailed": test_case.submission.build_failed,
                "buildLogEntries": [{"message": line} for line in test_case.submission.build_log],
            }
    return request
