"""Tests for StatusCallback.execute_command — the synchronous mid-pipeline command round-trip.

The combined-view point-out tool calls this to ask Artemis to navigate the client and learn the
real outcome. These tests cover the Artemis wire contract (URL derivation, auth header, timeout,
camelCased body) and that every failure mode degrades to "not applied" so the pipeline never hangs
or crashes on a command.
"""

# pylint: skip-file

import pytest
import requests

from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.point_out_command_dto import (
    PointOutCommandDTO,
    PointOutParametersDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum
from iris.web.status.status_update import COMMAND_TIMEOUT_SECONDS, StatusCallback


class _Response:
    def __init__(self, json_body):
        self._json_body = json_body

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self._json_body, Exception):
            raise self._json_body
        return self._json_body


def _callback(
    url="https://artemis.example/pipelines/chat/runs/run-1/status",
) -> StatusCallback:
    return StatusCallback(
        url=url,
        run_id="run-1",
        status=ChatStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
    )


def _command() -> PointOutCommandDTO:
    return PointOutCommandDTO(
        parameters=PointOutParametersDTO(lecture_unit_id=42, page=3)
    )


def test_applied_true_round_trip(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response({"applied": True})

    monkeypatch.setattr(requests, "post", fake_post)

    result = _callback().execute_command(_command())

    assert result.applied is True
    # The command endpoint is the sibling of the status endpoint.
    assert (
        captured["url"] == "https://artemis.example/pipelines/chat/runs/run-1/command"
    )
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer run-1"
    assert captured["kwargs"]["timeout"] == COMMAND_TIMEOUT_SECONDS
    # Body is camelCased by alias for the Artemis wire format.
    assert captured["kwargs"]["json"] == {
        "type": "pointOut",
        "parameters": {"lectureUnitId": 42, "page": 3},
    }


def test_applied_false_is_reported(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: _Response({"applied": False})
    )
    assert _callback().execute_command(_command()).applied is False


@pytest.mark.parametrize(
    "post",
    [
        # Transport error / timeout: the pipeline must not hang or raise.
        pytest.param(
            lambda url, **kwargs: (_ for _ in ()).throw(
                requests.exceptions.Timeout("timed out")
            ),
            id="timeout",
        ),
        # Response body missing the required "applied" field -> validation fails.
        pytest.param(lambda url, **kwargs: _Response({}), id="malformed-body"),
        pytest.param(
            lambda url, **kwargs: _Response(ValueError("no json")), id="invalid-json"
        ),
    ],
)
def test_failures_degrade_to_not_applied(monkeypatch, post):
    monkeypatch.setattr(requests, "post", post)
    assert _callback().execute_command(_command()).applied is False


def test_url_without_status_suffix_is_not_applied_without_posting(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: calls.append(url))

    result = _callback(url="https://artemis.example/no-suffix").execute_command(
        _command()
    )

    assert result.applied is False
    assert calls == []
