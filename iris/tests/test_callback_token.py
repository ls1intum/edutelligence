"""The callback token Artemis issues per run must never leave Iris except as the Authorization header."""

import json
import socket
from unittest.mock import patch

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from langfuse._utils.serializer import EventSerializer
from pydantic import BaseModel, ValidationError
from sentry_sdk.transport import Transport

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.callback_token import MASK, CallbackToken  # noqa: E402
from iris.domain.pipeline_execution_settings_dto import (  # noqa: E402
    PipelineExecutionSettingsDTO,
)
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO  # noqa: E402
from iris.domain.status.run_state_dto import RunStateEnum  # noqa: E402
from iris.sentry import credential_safety_options  # noqa: E402
from iris.web.status.status_update import ChatRunCallback  # noqa: E402
from iris.web.validation_errors import validation_exception_handler  # noqa: E402

SECRET = "eyJhbGciOiJIUzUxMiJ9.SECRET-PAYLOAD.SIGNATURE"  # pragma: allowlist secret


def _settings(**overrides) -> PipelineExecutionSettingsDTO:
    raw = {
        "authenticationToken": SECRET,
        "runId": "run-1",
        "artemisBaseUrl": "https://artemis.example",
    }
    raw.update(overrides)
    return PipelineExecutionSettingsDTO.model_validate(raw)


def test_the_token_is_only_revealed_on_request():
    token = _settings().authentication_token

    assert token.reveal() == SECRET
    assert token.authorization_header() == f"Bearer {SECRET}"
    assert SECRET not in repr(token)
    assert SECRET not in str(token)
    assert SECRET not in f"{token}"


def test_dumping_the_settings_never_shows_the_token():
    settings = _settings()

    assert SECRET not in repr(settings)
    assert settings.model_dump()["authentication_token"] == MASK
    assert SECRET not in settings.model_dump_json(by_alias=True)
    assert SECRET not in str(settings.model_dump(mode="json"))


def test_the_tracing_serializer_never_sees_the_token():
    """Langfuse records observed function arguments by dumping models and walking objects."""
    settings = _settings()
    callback = ChatRunCallback(
        run_id=settings.callback_run_id,
        base_url="https://artemis.example",
        auth_token=settings.authentication_token,
    )

    class Holder(BaseModel):
        settings: PipelineExecutionSettingsDTO

    serialized = json.dumps(
        {"args": [Holder(settings=settings), callback, settings.authentication_token]},
        cls=EventSerializer,
    )

    assert SECRET not in serialized
    assert "run-1" in serialized


def test_run_id_and_token_are_separate_and_older_artemis_uses_the_token_as_run_id():
    assert _settings().callback_run_id == "run-1"
    older = PipelineExecutionSettingsDTO.model_validate(
        {"authenticationToken": "legacy-value", "artemisBaseUrl": "https://a"}
    )
    assert older.callback_run_id == "legacy-value"


def test_an_empty_token_is_rejected():
    with pytest.raises(ValidationError):
        _settings(authenticationToken="")
    with pytest.raises(ValueError):
        CallbackToken("")


def test_equal_tokens_compare_equal_without_exposing_the_value():
    assert CallbackToken(SECRET) == CallbackToken(SECRET)
    assert CallbackToken(SECRET) != CallbackToken("other")
    assert CallbackToken(SECRET) != SECRET


def test_the_callback_sends_the_token_only_as_bearer_and_the_run_id_in_the_url():
    callback = ChatRunCallback(
        run_id="run-1",
        base_url="https://artemis.example",
        auth_token=CallbackToken(SECRET),
    )

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

    with patch("requests.post", return_value=_Response()) as post:
        callback.finish()

    url = post.call_args.args[0]
    assert url.endswith("/chat/runs/run-1/status")
    assert SECRET not in url
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(post.call_args.kwargs["json"])


# --------------------------------------------------------------------------- Sentry


class _CapturingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope.serialize().decode("utf-8", "replace"))


@pytest.fixture
def sentry_events():
    transport = _CapturingTransport()
    sentry_sdk.init(
        dsn="http://public@127.0.0.1:9/1",
        transport=transport,
        send_default_pii=True,
        max_request_body_size="always",
        default_integrations=False,
        **credential_safety_options(),
    )
    try:
        yield transport.envelopes
    finally:
        sentry_sdk.flush()
        sentry_sdk.init(dsn=None)


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_failed_callback_reports_to_sentry_without_the_token(sentry_events):
    """A real connection failure: the token is in the request the HTTP client built."""
    callback = ChatRunCallback(
        run_id="run-1",
        base_url=f"http://127.0.0.1:{_closed_port()}",
        auth_token=CallbackToken(SECRET),
    )
    callback.status = ChatStatusUpdateDTO(run_state=RunStateEnum.RUNNING)

    callback.fail("boom")
    sentry_sdk.flush()

    assert sentry_events, "the failure must be reported"
    assert all(SECRET not in envelope for envelope in sentry_events)
    assert any("run-1" in envelope for envelope in sentry_events)


def test_an_exception_with_the_settings_and_the_raw_job_in_scope_carries_no_token(
    sentry_events,
):
    def run():
        settings = _settings()  # noqa: F841  pylint: disable=unused-variable
        raw_job = {  # noqa: F841  pylint: disable=unused-variable
            "settings": {"authenticationToken": SECRET}
        }
        raise RuntimeError("pipeline failed")

    try:
        run()
    except RuntimeError as e:
        sentry_sdk.capture_exception(e)
    sentry_sdk.flush()

    assert sentry_events
    assert all(SECRET not in envelope for envelope in sentry_events)


def test_request_bodies_with_the_token_are_scrubbed():
    scrubber = credential_safety_options()["event_scrubber"]
    event = {
        "request": {
            "data": {
                "settings": {"authenticationToken": SECRET, "runId": "run-1"},
                "jobs": [{"settings": {"authenticationToken": SECRET}}],
            }
        }
    }

    scrubber.scrub_event(event)

    assert SECRET not in str(event)
    assert "run-1" in str(event)


# --------------------------------------------------------------------------- 422


def test_a_validation_error_neither_returns_nor_logs_the_token(caplog):
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    class Body(BaseModel):
        settings: PipelineExecutionSettingsDTO

    @app.post("/run")
    def run(body: Body):  # pylint: disable=unused-argument
        return {}

    client = TestClient(app)
    # artemisBaseUrl is missing, so the error quotes the settings object it was missing from.
    response = client.post("/run", json={"settings": {"authenticationToken": SECRET}})

    assert response.status_code == 422
    assert SECRET not in response.text
    assert "artemisBaseUrl" in response.text
    assert SECRET not in caplog.text
