import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import requests

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.pipeline_execution_settings_dto import (  # noqa: E402
    PipelineExecutionSettingsDTO,
)
from iris.domain.status.stage_dto import StageDTO  # noqa: E402
from iris.domain.status.stage_state_dto import StageStateEnum  # noqa: E402
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.web.status.partial_result_sender import (  # noqa: E402
    PARTIAL_POST_TIMEOUT_SECONDS,
    STOP_DRAIN_TIMEOUT_SECONDS,
    PartialResultSender,
)


def _build_model(**overrides):
    base = {
        "id": "test-model",
        "type": "openai_chat",
        "model": "gpt-test",
        "api_key": "sk-test",  # pragma: allowlist secret
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def _http_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
    )


def _chunk(content=None, tool_calls=None, usage=None):
    choices = []
    if content is not None or tool_calls is not None:
        choices.append(
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=None,
            )
        )
    return SimpleNamespace(choices=choices, usage=usage)


def _tool_delta(index, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _mock_openai_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant",
                    content="ok",
                    tool_calls=None,
                    refusal=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _mock_responses_response(
    *,
    output=None,
    output_text="ok",
    input_tokens=1,
    output_tokens=1,
    status="completed",
):
    return SimpleNamespace(
        status=status,
        output=(
            output
            if output is not None
            else [
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            text=output_text,
                        )
                    ],
                )
            ]
        ),
        output_text=output_text,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


def _responses_event(event_type, **kwargs):
    return SimpleNamespace(type=event_type, **kwargs)


def _responses_function_call(
    call_id="call_1", name="lookup", arguments='{"query": "iris"}'
):
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def test_pipeline_execution_settings_accepts_stream_response_flag():
    dto = PipelineExecutionSettingsDTO.model_validate(
        {
            "authenticationToken": "run-1",
            "artemisBaseUrl": "https://artemis.example",
            "streamResponse": True,
        }
    )

    assert dto.stream_response is True
    assert dto.model_dump(by_alias=True)["streamResponse"] is True


def test_pipeline_execution_settings_defaults_stream_response_to_false():
    dto = PipelineExecutionSettingsDTO.model_validate(
        {
            "authenticationToken": "run-1",
            "artemisBaseUrl": "https://artemis.example",
        }
    )

    assert dto.stream_response is False


def test_openai_streaming_forwards_content_deltas_and_usage():
    model = _build_model()
    mock_client = MagicMock()
    handler_events = []
    mock_client.chat.completions.create.return_value = iter(
        [
            _chunk(content="Hel"),
            _chunk(content="lo"),
            _chunk(usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2)),
        ]
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["Hel", "lo"]
    assert result.contents[0].text_content == "Hello"
    assert result.token_usage.model_info == "gpt-test"
    assert result.token_usage.num_input_tokens == 3
    assert result.token_usage.num_output_tokens == 2
    assert mock_client.chat.completions.create.call_args.kwargs["stream"] is True
    assert mock_client.chat.completions.create.call_args.kwargs["stream_options"] == {
        "include_usage": True
    }


def test_openai_streaming_resets_on_tool_call_and_returns_tool_call_message():
    model = _build_model()
    mock_client = MagicMock()
    handler_events = []
    mock_client.chat.completions.create.return_value = iter(
        [
            _chunk(content="Let me check."),
            _chunk(
                tool_calls=[
                    _tool_delta(
                        0,
                        call_id="call_1",
                        name="lookup",
                        arguments='{"query"',
                    )
                ]
            ),
            _chunk(tool_calls=[_tool_delta(0, arguments=':"iris"}')]),
            _chunk(content="This must not be forwarded."),
            _chunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=4)),
        ]
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["Let me check.", None]
    assert result.contents[0].text_content == ""
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].function.name == "lookup"
    assert result.tool_calls[0].function.arguments == {"query": "iris"}
    assert result.token_usage.num_input_tokens == 7
    assert result.token_usage.num_output_tokens == 4


def test_openai_streaming_resets_and_retries_after_retryable_mid_stream_error():
    model = _build_model()
    mock_client = MagicMock()
    handler_events = []
    rate_limit_error = openai.RateLimitError(
        "rate limited",
        response=_http_response(429),
        body=None,
    )

    def broken_stream():
        yield _chunk(content="stale")
        raise rate_limit_error

    mock_client.chat.completions.create.side_effect = [
        broken_stream(),
        iter(
            [
                _chunk(content="fresh"),
                _chunk(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)),
            ]
        ),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["stale", None, "fresh"]
    assert result.contents[0].text_content == "fresh"
    assert mock_client.chat.completions.create.call_count == 2
    sleep.assert_called_once()


def test_openai_chat_without_handler_uses_existing_non_streaming_params():
    model = _build_model()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [],
            CompletionArguments(temperature=0.2),
            tools=None,
        )

    assert result.contents[0].text_content == "ok"
    assert mock_client.chat.completions.create.call_args.kwargs == {
        "model": "gpt-test",
        "messages": [],
        "temperature": 0.2,
    }


def test_responses_streaming_forwards_text_deltas_and_usage():
    model = _build_model(use_responses_api=True)
    mock_client = MagicMock()
    handler_events = []
    mock_client.responses.create.return_value = iter(
        [
            _responses_event("response.output_text.delta", delta="Hel"),
            _responses_event("response.output_text.delta", delta="lo"),
            _responses_event(
                "response.completed",
                response=_mock_responses_response(
                    output_text="Hello",
                    input_tokens=3,
                    output_tokens=2,
                ),
            ),
        ]
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["Hel", "lo"]
    assert result.contents[0].text_content == "Hello"
    assert result.token_usage.model_info == "gpt-test"
    assert result.token_usage.num_input_tokens == 3
    assert result.token_usage.num_output_tokens == 2
    assert mock_client.responses.create.call_args.kwargs["stream"] is True
    mock_client.chat.completions.create.assert_not_called()


def test_responses_streaming_resets_on_tool_call_and_returns_tool_call_message():
    response_tool_call = _responses_function_call()
    model = _build_model(use_responses_api=True)
    mock_client = MagicMock()
    handler_events = []
    mock_client.responses.create.return_value = iter(
        [
            _responses_event("response.output_text.delta", delta="Let me check."),
            _responses_event(
                "response.output_item.added",
                item=SimpleNamespace(type="function_call"),
            ),
            _responses_event(
                "response.output_text.delta",
                delta="This must not be forwarded.",
            ),
            _responses_event(
                "response.completed",
                response=_mock_responses_response(
                    output=[response_tool_call],
                    output_text="",
                    input_tokens=7,
                    output_tokens=4,
                ),
            ),
        ]
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["Let me check.", None]
    assert result.contents[0].text_content == ""
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].function.name == "lookup"
    assert result.tool_calls[0].function.arguments == {"query": "iris"}
    assert result.token_usage.num_input_tokens == 7
    assert result.token_usage.num_output_tokens == 4


def test_responses_streaming_resets_and_retries_after_retryable_mid_stream_error():
    model = _build_model(use_responses_api=True)
    mock_client = MagicMock()
    handler_events = []
    rate_limit_error = openai.RateLimitError(
        "rate limited",
        response=_http_response(429),
        body=None,
    )

    def broken_stream():
        yield _responses_event("response.output_text.delta", delta="stale")
        raise rate_limit_error

    mock_client.responses.create.side_effect = [
        broken_stream(),
        iter(
            [
                _responses_event("response.output_text.delta", delta="fresh"),
                _responses_event(
                    "response.completed",
                    response=_mock_responses_response(
                        output_text="fresh",
                        input_tokens=1,
                        output_tokens=1,
                    ),
                ),
            ]
        ),
    ]

    with (
        patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client),
        patch("time.sleep") as sleep,
    ):
        result = model.chat(
            [],
            CompletionArguments(stream_handler=handler_events.append),
            tools=None,
        )

    assert handler_events == ["stale", None, "fresh"]
    assert result.contents[0].text_content == "fresh"
    assert mock_client.responses.create.call_count == 2
    sleep.assert_called_once()


def test_openai_chat_dispatches_by_responses_flag_and_stream_handler():
    responses_stream_model = _build_model(use_responses_api=True)
    responses_stream_client = MagicMock()
    responses_stream_client.responses.create.return_value = iter(
        [
            _responses_event(
                "response.completed",
                response=_mock_responses_response(output_text="streamed"),
            )
        ]
    )

    with patch.object(
        DirectOpenAIChatModel,
        "get_client",
        lambda self: responses_stream_client,
    ):
        responses_stream_model.chat(
            [],
            CompletionArguments(stream_handler=lambda _delta: None),
            tools=None,
        )

    assert responses_stream_client.responses.create.call_args.kwargs["stream"] is True
    responses_stream_client.chat.completions.create.assert_not_called()

    responses_model = _build_model(use_responses_api=True)
    responses_client = MagicMock()
    responses_client.responses.create.return_value = _mock_responses_response(
        output_text="non-streamed"
    )

    with patch.object(
        DirectOpenAIChatModel, "get_client", lambda self: responses_client
    ):
        responses_model.chat([], CompletionArguments(), tools=None)

    assert "stream" not in responses_client.responses.create.call_args.kwargs
    responses_client.chat.completions.create.assert_not_called()

    chat_stream_model = _build_model()
    chat_stream_client = MagicMock()
    chat_stream_client.chat.completions.create.return_value = iter(
        [_chunk(content="chat")]
    )

    with patch.object(
        DirectOpenAIChatModel,
        "get_client",
        lambda self: chat_stream_client,
    ):
        chat_stream_model.chat(
            [],
            CompletionArguments(stream_handler=lambda _delta: None),
            tools=None,
        )

    assert chat_stream_client.chat.completions.create.call_args.kwargs["stream"] is True
    chat_stream_client.responses.create.assert_not_called()


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def test_partial_result_sender_clears_draft_on_reset_and_stops():
    posts = []
    statuses = []
    stages = [
        StageDTO(weight=1, state=StageStateEnum.IN_PROGRESS, name="Thinking"),
        StageDTO(weight=1, state=StageStateEnum.NOT_STARTED, name="Memory"),
    ]

    def fake_post(url, headers, json, timeout):
        posts.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        status = statuses.pop(0) if statuses else 200
        return _Response(status)

    with patch("iris.web.status.partial_result_sender.requests.post", fake_post):
        sender = PartialResultSender(
            "https://artemis.example/api/iris/internal/pipelines/chat/runs/run-1/status",
            "run-1",
            stages,
            interval_seconds=0.01,
        )
        sender.start()
        sender.on_delta("Hel")
        sender.on_delta("lo")
        _wait_until(lambda: len(posts) == 1)

        # A reset (e.g. tool-call preamble or a retried stream) must clear the
        # visible draft by emitting an empty partial with a higher partialSeq,
        # not just wipe local state.
        sender.on_delta(None)
        _wait_until(lambda: len(posts) == 2)

        # A second reset with no draft currently visible must be suppressed so
        # we do not spam Artemis with redundant empty clears.
        sender.on_delta(None)
        time.sleep(0.03)
        assert len(posts) == 2

        sender.on_delta("Fresh")
        _wait_until(lambda: len(posts) == 3)

        sender.stop()
        sender.on_delta(" after stop")
        time.sleep(0.03)

    assert len(posts) == 3
    assert [post["json"]["partialSeq"] for post in posts] == [1, 2, 3]
    assert [post["json"]["partialResult"] for post in posts] == ["Hello", "", "Fresh"]
    assert posts[0]["headers"]["Authorization"] == "Bearer run-1"
    assert posts[0]["timeout"] == PARTIAL_POST_TIMEOUT_SECONDS
    assert posts[0]["json"]["stages"][0]["state"] == "IN_PROGRESS"
    assert posts[1]["json"]["stages"] == posts[0]["json"]["stages"]


def test_partial_post_timeout_is_bounded_by_stop_drain_budget():
    # The stop drain budget must strictly exceed the per-POST timeout, otherwise
    # stop() could return while a partial POST is still in flight and let a
    # stale partial land after the final result.
    assert PARTIAL_POST_TIMEOUT_SECONDS < STOP_DRAIN_TIMEOUT_SECONDS


def test_stop_waits_for_in_flight_partial_post_to_drain():
    started: list[int] = []
    completed: list[int] = []
    post_started = threading.Event()
    stages = [StageDTO(weight=1, state=StageStateEnum.IN_PROGRESS, name="Thinking")]

    def slow_post(url, headers, json, timeout):  # pylint: disable=unused-argument
        started.append(json["partialSeq"])
        post_started.set()
        # Simulate a POST that is still in flight when stop() is called. The
        # sleep stays well under STOP_DRAIN_TIMEOUT_SECONDS so the drain budget
        # covers it.
        time.sleep(0.3)
        completed.append(json["partialSeq"])
        return _Response(200)

    with patch("iris.web.status.partial_result_sender.requests.post", slow_post):
        sender = PartialResultSender(
            "https://artemis.example/api/iris/internal/pipelines/chat/runs/run-1/status",
            "run-1",
            stages,
            interval_seconds=0.01,
        )
        sender.start()
        sender.on_delta("Hello")
        # Ensure a POST is genuinely in flight before we stop.
        assert post_started.wait(1.0)

        sender.stop()

        # stop() must not return until the in-flight POST has drained and the
        # worker thread has fully exited, so no partial can land after the
        # final result the pipeline sends next.
        assert not sender.is_alive()
        assert started == completed
        assert completed  # the in-flight post actually completed


def test_partial_result_sender_stops_permanently_on_404():
    posts = []
    stages = [StageDTO(weight=1, state=StageStateEnum.IN_PROGRESS, name="Thinking")]

    def fake_post(url, headers, json, timeout):  # pylint: disable=unused-argument
        posts.append(json)
        return _Response(404)

    with patch("iris.web.status.partial_result_sender.requests.post", fake_post):
        sender = PartialResultSender(
            "https://artemis.example/api/iris/internal/pipelines/chat/runs/run-1/status",
            "run-1",
            stages,
            interval_seconds=0.01,
        )
        sender.start()
        sender.on_delta("gone")
        _wait_until(lambda: not sender.is_alive())
        sender.on_delta("ignored")
        time.sleep(0.03)
        sender.stop()

    assert len(posts) == 1


def _make_dto(stream_response_marker):
    class Settings(SimpleNamespace):
        def is_local(self):
            return False

    if stream_response_marker == "absent":
        settings = Settings(
            authentication_token="run-1",
            artemis_base_url="https://artemis.example",
        )
    else:
        settings = Settings(
            authentication_token="run-1",
            artemis_base_url="https://artemis.example",
            stream_response=stream_response_marker,
        )
    return SimpleNamespace(
        chat_history=[],
        user=SimpleNamespace(id=1, lang_key="en", memiris_enabled=False),
        course=SimpleNamespace(
            id=7,
            name="Test Course",
            competencies=[],
            exercises=[],
            student_analytics_dashboard_enabled=False,
        ),
        lecture=None,
        programming_exercise=None,
        text_exercise=None,
        settings=settings,
        session_title=None,
        metrics=None,
        context=None,
        custom_instructions="",
    )


def _make_pipeline(chat_mode: IrisChatMode) -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = chat_mode
    pipeline.event = None

    title_pipeline = MagicMock(return_value="UPDATE: Fancy Title")
    title_pipeline.tokens = None
    pipeline.session_title_pipeline = title_pipeline

    citation_pipeline = MagicMock()
    citation_pipeline.tokens = []
    pipeline.citation_pipeline = citation_pipeline

    suggestion_pipeline = MagicMock(return_value=["suggestion 1"])
    suggestion_pipeline.tokens = None
    pipeline.suggestion_pipeline = suggestion_pipeline

    pipeline.mcq_pipeline = MagicMock()
    pipeline.prepare_state = lambda state: None
    pipeline.build_system_message = lambda state: "system prompt"
    pipeline.get_tools = lambda state: []
    pipeline.execute_agent = lambda state: "agent answer"
    pipeline.create_tracing_context = lambda dto, variant: None
    return pipeline


def _make_callback(events):
    stage = StageDTO(weight=1, state=StageStateEnum.NOT_STARTED, name="Thinking")
    callback = MagicMock()
    callback.url = (
        "https://artemis.example/api/iris/internal/pipelines/chat/runs/run-1/status"
    )
    callback.run_id = "run-1"
    callback.stage = stage
    callback.status = SimpleNamespace(stages=[stage])

    def in_progress(*_args, **_kwargs):
        stage.state = StageStateEnum.IN_PROGRESS

    callback.in_progress.side_effect = in_progress
    callback.done.side_effect = lambda *_args, **_kwargs: events.append("callback.done")
    return callback


def _run_stubbed_pipeline(stream_response_marker):
    events = []
    created_args = []
    sender_instances = []

    class FakeLlm:
        def __init__(self, request_handler, completion_args, **_kwargs):
            self.request_handler = request_handler
            self.completion_args = completion_args
            self.tokens = None
            created_args.append(completion_args)

    class FakeSender:
        """Stands in for PartialResultSender to record wiring calls."""

        def __init__(self, url, run_id, stages_snapshot, interval_seconds=0.35):
            self.url = url
            self.run_id = run_id
            self.stages_snapshot = stages_snapshot
            self.interval_seconds = interval_seconds
            sender_instances.append(self)

        def start(self):
            events.append("sender.start")

        def stop(self):
            events.append("sender.stop")

        def on_delta(self, delta):  # pylint: disable=unused-argument
            events.append("sender.delta")

    variant = MagicMock()
    variant.id = "default"
    variant.model.return_value = "some-model-id"
    callback = _make_callback(events)
    pipeline = _make_pipeline(IrisChatMode.LECTURE)

    with (
        patch("iris.pipeline.abstract_agent_pipeline.VectorDatabase"),
        patch("iris.pipeline.abstract_agent_pipeline.MemirisWrapper"),
        patch("iris.pipeline.abstract_agent_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.abstract_agent_pipeline.IrisLangchainChatModel", FakeLlm),
        patch("iris.pipeline.abstract_agent_pipeline.PartialResultSender", FakeSender),
    ):
        pipeline(_make_dto(stream_response_marker), variant, callback)

    return events, created_args, sender_instances


def test_pipeline_wires_partial_sender_when_stream_response_is_enabled():
    events, created_args, sender_instances = _run_stubbed_pipeline(True)

    assert len(sender_instances) == 1
    sender = sender_instances[0]
    assert sender.url.endswith("/chat/runs/run-1/status")
    assert sender.run_id == "run-1"
    assert sender.stages_snapshot[0].state == StageStateEnum.IN_PROGRESS
    assert created_args[0].stream_handler == sender.on_delta
    assert events.index("sender.start") < events.index("sender.stop")
    assert events.index("sender.stop") < events.index("callback.done")


def test_pipeline_does_not_create_sender_when_stream_response_is_absent():
    events, created_args, sender_instances = _run_stubbed_pipeline("absent")

    assert "sender.start" not in events
    assert not sender_instances
    assert created_args[0].stream_handler is None
