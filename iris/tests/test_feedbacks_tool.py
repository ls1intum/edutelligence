"""Tests for the get_feedbacks tool: tri-state test outcome + non-test marking.

``tests/conftest.py`` sets ``APPLICATION_YML_PATH`` before pipeline imports; importing the
tool factory + DTO here is safe (matching the other tool tests).
"""

from unittest.mock import MagicMock

from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.tools.feedbacks import create_tool_get_feedbacks


def _submission_with_feedbacks(feedbacks):
    return ProgrammingSubmissionDTO.model_validate(
        {
            "id": 1,
            "isPractice": False,
            "buildFailed": False,
            "latestResult": {"feedbacks": feedbacks},
        }
    )


def test_get_feedbacks_renders_tristate_and_marks_non_test():
    sub = _submission_with_feedbacks(
        [
            {
                "testCaseName": "tPass",
                "credits": 1,
                "positive": True,
                "hasTestCase": True,
            },
            {
                "testCaseName": "tFail",
                "credits": 0,
                "positive": False,
                "hasTestCase": True,
            },
            # positive absent -> None -> not executed (must NOT be shown as FAIL)
            {"testCaseName": "tNotRun", "credits": 0, "hasTestCase": True},
            {
                "testCaseName": "sca",
                "credits": 0,
                "positive": False,
                "hasTestCase": False,
            },
        ]
    )
    out = create_tool_get_feedbacks(sub, MagicMock())()
    assert "tPass. PASS (test case)" in out
    assert "tFail. FAIL (test case)" in out
    assert "tNotRun. NOT EXECUTED (test case)" in out
    assert "sca. non-test feedback" in out
    # a not-executed test must never be rendered as a failure
    assert "tNotRun. FAIL" not in out


def test_get_feedbacks_no_result_reports_none_available():
    sub = ProgrammingSubmissionDTO.model_validate(
        {"id": 1, "isPractice": False, "buildFailed": False}
    )
    assert create_tool_get_feedbacks(sub, MagicMock())() == "No feedbacks available."


def test_get_feedbacks_omits_outcome_when_artemis_did_not_send_the_field():
    """
    Compatibility with every Artemis release before ls1intum/Artemis#13023, whose
    ``PyrisFeedbackDTO`` is ``(text, testCaseName, credits)`` and sends no ``hasTestCase``.
    Defaulting the missing field to False marked genuine test results as "non-test feedback",
    and this tool is shared with the exercise chat and the tutor-suggestion pipeline, so the
    claim would have reached those pipelines too. Unknown must render the pre-field line.
    """
    sub = _submission_with_feedbacks(
        [{"testCaseName": "testBubbleSort", "credits": 1.0, "text": "ok"}]
    )
    out = create_tool_get_feedbacks(sub, MagicMock())()
    assert "Case: testBubbleSort. Credits: 1.0. Info: ok" in out
    assert "non-test feedback" not in out
    assert "PASS" not in out and "FAIL" not in out and "NOT EXECUTED" not in out


def test_get_feedbacks_absent_field_is_distinct_from_explicit_false():
    """The tri-state must stay a tri-state: an explicit hasTestCase=false is still a claim."""
    unknown = create_tool_get_feedbacks(
        _submission_with_feedbacks([{"testCaseName": "t", "credits": 0.0}]), MagicMock()
    )()
    explicit = create_tool_get_feedbacks(
        _submission_with_feedbacks(
            [{"testCaseName": "t", "credits": 0.0, "hasTestCase": False}]
        ),
        MagicMock(),
    )()
    assert "non-test feedback" not in unknown
    assert "non-test feedback" in explicit
