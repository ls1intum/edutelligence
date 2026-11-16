"""Translates a test case into the chat request Artemis sends to Pyris (ChatPipelineExecutionDTO).

All content comes from the test case. Only the run settings (callback address, token, variant,
support level, cloud or local models) are added by the benchmark.
"""

from typing import Any, Optional

from ..evaluation_pipeline.models import ChatMode, Exercise, Result, Submission, TestCase

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
        "user": {"id": test_case.user.id, "langKey": test_case.user.language},
        "course": {
            "id": test_case.course.id,
            "name": test_case.course.name,
            "description": test_case.course.description,
        },
        # the last message is the student message Iris has to answer
        "chatHistory": [
            {"sender": SENDER[m.sender], "contents": [{"textContent": m.text}]}
            for m in test_case.conversation
        ],
    }
    if test_case.chat_mode == ChatMode.PROGRAMMING_EXERCISE and test_case.exercise:
        request["programmingExercise"] = _exercise(test_case.exercise)
        if test_case.submission:
            request["programmingExerciseSubmission"] = _submission(test_case.submission)
    return request


def _exercise(exercise: Exercise) -> dict[str, Any]:
    return {
        "id": exercise.id,
        "title": exercise.title,
        "problemStatement": exercise.problem_statement,
        "programmingLanguage": exercise.programming_language,
        "startDate": _iso(exercise.start_date),
        "endDate": _iso(exercise.end_date),
        "maxPoints": exercise.max_points,
        "templateRepository": exercise.template_repository,
        "solutionRepository": exercise.solution_repository,
    }


def _submission(submission: Submission) -> dict[str, Any]:
    return {
        "id": submission.id,
        "date": _iso(submission.date),
        "repository": submission.repository,
        "isPractice": False,
        "buildFailed": submission.build_failed,
        "buildLogEntries": [{"message": line} for line in submission.build_log],
        "latestResult": _result(submission.latest_result),
    }


def _result(result: Optional[Result]) -> Optional[dict[str, Any]]:
    if result is None:
        return None
    return {
        "completionDate": _iso(result.completion_date),
        "successful": result.successful,
        "feedbacks": [
            {
                "testCaseName": f.test_case_name,
                "text": f.text,
                "credits": f.credits,
                "positive": f.passed,
                "hasTestCase": f.test_case_name is not None,
            }
            for f in result.feedbacks
        ],
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None
