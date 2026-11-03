"""The callback token Artemis issues per run must never leave Iris except as the Authorization header."""

import http.server
import io
import json
import logging
import socket
import threading
from collections import OrderedDict
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
from iris.common import callback_token as callback_token_module  # noqa: E402
from iris.common.callback_token import (  # noqa: E402
    MASK,
    CallbackToken,
    register_legacy_run_token,
    scrub_callback_credentials,
)
from iris.common.logging_config import IrisFormatter  # noqa: E402
from iris.domain.pipeline_execution_settings_dto import (  # noqa: E402
    PipelineExecutionSettingsDTO,
)
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO  # noqa: E402
from iris.domain.status.run_state_dto import RunStateEnum  # noqa: E402
from iris.sentry import credential_safety_options  # noqa: E402
from iris.tracing.langfuse_tracer import mask_callback_credentials  # noqa: E402
from iris.web.status.ingestion_status_callback import (  # noqa: E402
    IngestionStatusCallback,
)
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


def test_the_trace_run_id_never_contains_the_token():
    assert _settings().trace_run_id == "run-1"
    older = PipelineExecutionSettingsDTO.model_validate(
        {"authenticationToken": SECRET, "artemisBaseUrl": "https://a"}
    )
    assert SECRET not in older.trace_run_id
    assert older.trace_run_id.startswith("run-")
    assert older.trace_run_id == older.model_copy().trace_run_id


def test_the_langfuse_session_is_the_run_id_or_a_hash_without_runid():
    """Older Artemis versions send no run id; the session id must not fall back to the token."""
    # pylint: disable=import-outside-toplevel
    from iris.tracing.langfuse_tracer import TracingContext

    class Dto(BaseModel):
        settings: PipelineExecutionSettingsDTO

    with_run_id = TracingContext.from_dto(Dto(settings=_settings()), "chat")
    without_run_id = TracingContext.from_dto(
        Dto(
            settings=PipelineExecutionSettingsDTO.model_validate(
                {"authenticationToken": SECRET, "artemisBaseUrl": "https://a"}
            )
        ),
        "chat",
    )

    assert with_run_id.session_id == "run-1"
    assert without_run_id.session_id is not None
    assert SECRET not in without_run_id.session_id


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


def test_the_ingestion_callback_sends_the_token_only_as_bearer_and_the_run_id_in_the_url():
    callback = IngestionStatusCallback(
        run_id="run-1",
        base_url="https://artemis.example",
        lecture_unit_id=7,
        auth_token=CallbackToken(SECRET),
    )

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

    with patch(
        "iris.web.status.ingestion_status_callback.http_requests.post",
        return_value=_Response(),
    ) as post:
        callback.fail("boom")

    url = post.call_args.args[0]
    assert (
        url
        == "https://artemis.example/api/iris/internal/webhooks/ingestion/runs/run-1/status"
    )
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


# --------------------------------------------------------------------------- Artemis without run ids

LEGACY = (
    "artemis_example_org-node1-1760000000000-AbCdE12345"  # pragma: allowlist secret
)


def _legacy_settings() -> PipelineExecutionSettingsDTO:
    return PipelineExecutionSettingsDTO.model_validate(
        {"authenticationToken": LEGACY, "artemisBaseUrl": "https://artemis.example"}
    )


def _legacy_callback() -> ChatRunCallback:
    settings = _legacy_settings()
    return ChatRunCallback(
        run_id=settings.callback_run_id,
        base_url="https://artemis.example",
        auth_token=settings.authentication_token,
    )


def test_without_run_id_the_token_is_only_in_the_url_older_artemis_expects():
    callback = _legacy_callback()

    assert LEGACY in callback.url
    assert LEGACY not in callback.run_id
    assert callback.run_id == _legacy_settings().trace_run_id


def test_without_run_id_the_traced_inputs_carry_no_token():
    """What Langfuse receives for an observed pipeline call with the DTO and the callback."""
    traced = mask_callback_credentials(
        data={
            "args": [_legacy_settings(), _legacy_callback()],
            "kwargs": {"callback": _legacy_callback(), "url": _legacy_callback().url},
        }
    )

    assert LEGACY not in json.dumps(traced)
    assert _legacy_settings().trace_run_id in json.dumps(traced)


def test_plain_run_ids_are_not_scrubbed():
    url = "https://a/api/iris/internal/pipelines/chat/runs/0b7c2f4e-5d2a-4f43-9d55-0d6c51a0a7e1/status"
    assert scrub_callback_credentials(url) == url


def test_without_run_id_a_failed_callback_reports_to_sentry_without_the_token(
    sentry_events,
):
    settings = _legacy_settings()
    callback = ChatRunCallback(
        run_id=settings.callback_run_id,
        base_url=f"http://127.0.0.1:{_closed_port()}",
        auth_token=settings.authentication_token,
    )

    callback.fail("boom")
    sentry_sdk.flush()

    assert sentry_events, "the failure must be reported"
    assert all(LEGACY not in envelope for envelope in sentry_events)


# An older Artemis used the client-generated UUID of a global search request as its token.
LEGACY_UUID = "4f1d2c3b-9a8e-4b7c-8d6e-5f4a3b2c1d0e"


def _legacy_uuid_callback(base_url="https://artemis.example") -> ChatRunCallback:
    return ChatRunCallback(
        run_id=LEGACY_UUID, base_url=base_url, auth_token=CallbackToken(LEGACY_UUID)
    )


def test_a_uuid_shaped_legacy_token_is_scrubbed_from_traces():
    callback = _legacy_uuid_callback()

    traced = mask_callback_credentials(data={"args": [callback], "url": callback.url})

    assert LEGACY_UUID in callback.url
    assert LEGACY_UUID not in json.dumps(traced)


def test_a_uuid_shaped_legacy_token_is_scrubbed_from_sentry_errors(sentry_events):
    callback = _legacy_uuid_callback(base_url=f"http://127.0.0.1:{_closed_port()}")

    callback.fail("boom")
    sentry_sdk.flush()

    assert sentry_events
    assert all(LEGACY_UUID not in envelope for envelope in sentry_events)


@pytest.mark.parametrize("token", [LEGACY, LEGACY_UUID])
def test_legacy_tokens_are_scrubbed_from_application_logs(token):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(IrisFormatter())
    status_logger = logging.getLogger("iris.web.status.status_update")
    status_logger.addHandler(handler)
    previous_level = status_logger.level
    status_logger.setLevel(logging.INFO)
    try:

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

        succeeding = ChatRunCallback(
            run_id=token,
            base_url="https://artemis.example",
            auth_token=CallbackToken(token),
        )
        with patch("requests.post", return_value=_Response()):
            succeeding.finish()
        failing = ChatRunCallback(
            run_id=token,
            base_url=f"http://127.0.0.1:{_closed_port()}",
            auth_token=CallbackToken(token),
        )
        with patch("iris.web.status.status_update.capture_exception"), patch(
            "iris.web.status.status_update.capture_message"
        ):
            failing.fail("boom")
    finally:
        status_logger.removeHandler(handler)
        status_logger.setLevel(previous_level)

    output = stream.getvalue()
    assert "Status callback to" in output, "the successful callback must be logged"
    assert "Error sending status update" in output, "the failure must be logged"
    assert token not in output


def test_a_legacy_token_is_scrubbed_from_sentry_transactions():
    """With tracing on, the HTTP span of a successful callback names its URL."""
    received = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # pylint: disable=invalid-name
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            received.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):  # pylint: disable=arguments-differ
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = _CapturingTransport()
    sentry_sdk.init(
        dsn="http://public@127.0.0.1:9/1",
        transport=transport,
        send_default_pii=True,
        traces_sample_rate=1.0,
        **credential_safety_options(),
    )
    try:
        callback = _legacy_uuid_callback(
            base_url=f"http://127.0.0.1:{server.server_port}"
        )
        with sentry_sdk.start_transaction(name="callback"):
            callback.finish()
        sentry_sdk.flush()
    finally:
        sentry_sdk.init(dsn=None)
        server.shutdown()

    assert received and LEGACY_UUID in received[0], "the callback must have been sent"
    assert any('"type":"transaction"' in envelope for envelope in transport.envelopes)
    assert all(LEGACY_UUID not in envelope for envelope in transport.envelopes)


def test_when_the_registry_overflows_every_run_id_segment_is_scrubbed(monkeypatch):
    """A token dropped from the full registry must still never pass as a run id."""
    monkeypatch.setattr(callback_token_module, "_LEGACY_TOKEN_LIMIT", 3)
    monkeypatch.setattr(callback_token_module, "_legacy_tokens", OrderedDict())
    monkeypatch.setattr(callback_token_module, "_legacy_tokens_dropped", False)
    kept = _legacy_uuid_callback()
    for index in range(3):
        register_legacy_run_token(f"other-legacy-token-{index}")

    traced = json.dumps(
        mask_callback_credentials(data={"args": [kept], "url": kept.url})
    )
    record = logging.LogRecord(
        "x", logging.INFO, "", 0, "Status callback to %s", (kept.url,), None
    )
    logged = IrisFormatter().format(record)
    event = credential_safety_options()["before_send"](
        {"message": f"Error sending status update to {kept.url}"}, None
    )

    assert LEGACY_UUID not in traced
    assert LEGACY_UUID not in logged
    assert LEGACY_UUID not in json.dumps(event)


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
