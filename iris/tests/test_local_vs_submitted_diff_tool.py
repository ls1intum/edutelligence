"""Tests for the local_vs_submitted_diff tool factory.

``tests/conftest.py`` sets ``APPLICATION_YML_PATH`` before pipeline imports; importing the
tool factory + DTO here is safe (matching the other tool tests).
"""

from unittest.mock import MagicMock

from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.tools.local_vs_submitted_diff import (
    _NO_CHANGES,
    _UNAVAILABLE,
    create_tool_local_vs_submitted_diff,
)


def _submission(repository, submitted_repository, available=True):
    return ProgrammingSubmissionDTO.model_validate(
        {
            "id": 1,
            "isPractice": False,
            "buildFailed": False,
            "repository": repository,
            "submittedRepository": submitted_repository,
            "submittedRepositoryAvailable": available,
        }
    )


def _tool(submission):
    callback = MagicMock()
    return create_tool_local_vs_submitted_diff(submission, callback), callback


def test_changed_file_shows_unified_diff_with_both_sides():
    sub = _submission({"P.java": "a\nFIXED\nc"}, {"P.java": "a\nOLD\nc"})
    tool, callback = _tool(sub)
    out = tool()
    assert "submitted/P.java" in out
    assert "local/P.java" in out
    assert "-OLD" in out
    assert "+FIXED" in out
    callback.in_progress.assert_called_once()


def test_new_local_code_file_shows_as_all_added():
    # submitted side "" (a brand-new local file) -> the whole file is an addition
    sub = _submission({"New.java": "line1\nline2"}, {"New.java": ""})
    tool, _ = _tool(sub)
    out = tool()
    assert "+line1" in out
    assert "+line2" in out


def test_empty_submitted_repository_but_readable_reports_no_changes():
    sub = _submission({"P.java": "unchanged"}, {}, available=True)
    tool, _ = _tool(sub)
    assert tool() == _NO_CHANGES


def test_submitted_repo_not_readable_reports_unavailable_not_no_changes():
    # Repo fetch failed -> submitted set empty AND not available. Must NOT be reported as "no changes".
    sub = _submission({"P.java": "code"}, {}, available=False)
    tool, _ = _tool(sub)
    assert tool() == _UNAVAILABLE


def test_none_submission_reports_unavailable():
    tool, _ = _tool(None)
    assert tool() == _UNAVAILABLE
