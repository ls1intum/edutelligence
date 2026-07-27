"""Tests for StatusCallback.execute_command — the synchronous mid-pipeline command round-trip.

The combined-view point-out tool calls this to ask Artemis to navigate the client and learn the
real outcome. These tests cover the HTTP transport concerns (URL derivation, headers, timeout) and
that every failure mode (transport error/timeout, malformed body, non-derivable URL) degrades to
"not applied" so the pipeline never hangs or crashes on a command.
"""

# pylint: skip-file

import requests

from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.command_dto import CommandDTO
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.domain.status.run_state_dto import RunStateEnum
from iris.web.status.status_update import COMMAND_TIMEOUT_SECONDS, StatusCallback


class _Response:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

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
    return PointOutCommandDTO(lecture_unit_id=42, page=3)


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
        "parameters": {
            "lectureUnitId": 42,
            "page": 3,
        },
    }


def test_generic_command_round_trip_keeps_extra_fields(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["kwargs"] = kwargs
        return _Response({"applied": True})

    monkeypatch.setattr(requests, "post", fake_post)

    command = CommandDTO(
        type="highlightTerm", parameters={"slide": 4, "term": "quicksort"}
    )
    result = _callback().execute_command(command)

    assert result.applied is True
    assert captured["kwargs"]["json"] == {
        "type": "highlightTerm",
        "parameters": {
            "slide": 4,
            "term": "quicksort",
        },
    }


def test_applied_false_is_reported(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: _Response({"applied": False})
    )
    assert _callback().execute_command(_command()).applied is False


def test_transport_timeout_degrades_to_not_applied(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(requests, "post", raise_timeout)
    assert _callback().execute_command(_command()).applied is False


def test_malformed_response_body_degrades_to_not_applied(monkeypatch):
    # Missing the required "applied" field -> validation fails -> treated as not applied.
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: _Response({}))
    assert _callback().execute_command(_command()).applied is False


def test_invalid_json_body_degrades_to_not_applied(monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: _Response(ValueError("no json"))
    )
    assert _callback().execute_command(_command()).applied is False


def test_url_without_status_suffix_is_not_applied_without_posting(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: calls.append(url))

    result = _callback(url="https://artemis.example/no-suffix").execute_command(
        _command()
    )

    assert result.applied is False
    assert calls == []
