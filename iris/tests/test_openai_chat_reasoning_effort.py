import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Bootstrap the iris package: importing iris.llm directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order — this
# mirrors what every working pipeline test already does transitively.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402


def _mock_openai_response():
    """Build a minimal response object with the attributes chat() inspects."""
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


def _build_model(**overrides):
    base = {
        "id": "test-model",
        "type": "openai_chat",
        "model": "gpt-test",
        "api_key": "sk-test",  # pragma: allowlist secret
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def _invoke_chat(model, **completion_kwargs):
    """Invoke chat() against a mocked client and return the kwargs that were
    passed to ``client.chat.completions.create``."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.chat.completions.create.call_args.kwargs


def test_reasoning_effort_dropped_when_model_does_not_support_it():
    model = _build_model()  # supports_reasoning_effort defaults to False
    params = _invoke_chat(model, reasoning_effort="high")
    assert "reasoning_effort" not in params


def test_reasoning_effort_not_forwarded_when_unset_even_if_model_supports_it():
    model = _build_model(supports_reasoning_effort=True)
    params = _invoke_chat(model)  # no reasoning_effort passed
    assert "reasoning_effort" not in params


def test_reasoning_effort_forwarded_when_model_supports_it_and_value_set():
    model = _build_model(supports_reasoning_effort=True)
    params = _invoke_chat(model, reasoning_effort="high")
    assert params["reasoning_effort"] == "high"


def test_temperature_dropped_for_reasoning_models():
    model = _build_model(is_reasoning_model=True)
    params = _invoke_chat(model, temperature=0.5)
    assert "temperature" not in params


def test_temperature_forwarded_for_non_reasoning_models():
    model = _build_model()  # is_reasoning_model defaults to False
    params = _invoke_chat(model, temperature=0.5)
    assert params["temperature"] == 0.5


def test_ignored_reasoning_effort_emits_debug_log(caplog):
    model = _build_model()  # supports_reasoning_effort=False
    with caplog.at_level(logging.DEBUG, logger="iris.llm.external.openai_chat"):
        _invoke_chat(model, reasoning_effort="medium")
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Ignoring reasoning_effort=medium" in msg
        and "id=test-model" in msg
        and "supports_reasoning_effort: true" in msg
        for msg in messages
    ), f"expected helpful debug log; got: {messages}"
