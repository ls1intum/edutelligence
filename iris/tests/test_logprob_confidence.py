import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Bootstrap the iris package: importing iris.llm directly hits a pre-existing
# circular import between iris.common.pyris_message and iris.domain. Loading
# iris.pipeline.pipeline first establishes the right module init order — this
# mirrors what every working pipeline test already does transitively.
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.pipeline.shared.confidence_scoring import (  # noqa: E402
    logprob_confidence,
    model_supports_logprobs,
)


# ──────────────────────────────────────────────────────────────────────────
# logprob_confidence: mean-logprob → exp() → [0, 1]
# ──────────────────────────────────────────────────────────────────────────
def test_logprob_confidence_empty_or_missing_is_zero():
    assert logprob_confidence(None) == 0.0
    assert logprob_confidence([]) == 0.0


def test_logprob_confidence_certain_tokens_is_one():
    assert logprob_confidence([0.0, 0.0, 0.0]) == 1.0


def test_logprob_confidence_is_exp_of_mean():
    logprobs = [-0.2, -0.4]
    assert logprob_confidence(logprobs) == math.exp(-0.3)


def test_logprob_confidence_clamped_to_unit_interval():
    # Strongly negative logprobs stay >= 0; positive (impossible) stay <= 1.
    assert 0.0 <= logprob_confidence([-10.0, -8.0]) <= 1.0
    assert logprob_confidence([1.0, 2.0]) == 1.0


# ──────────────────────────────────────────────────────────────────────────
# model_supports_logprobs: capability lookup via LlmManager
# ──────────────────────────────────────────────────────────────────────────
def test_model_supports_logprobs_true_when_entry_declares_support():
    manager = MagicMock()
    manager.get_llm_by_id.return_value = SimpleNamespace(supports_logprobs=True)
    with patch("iris.llm.llm_manager.LlmManager", return_value=manager):
        assert model_supports_logprobs("some-model") is True


def test_model_supports_logprobs_false_when_unsupported_or_unknown():
    manager = MagicMock()
    manager.get_llm_by_id.return_value = SimpleNamespace(supports_logprobs=False)
    with patch("iris.llm.llm_manager.LlmManager", return_value=manager):
        assert model_supports_logprobs("ollama-model") is False

    manager.get_llm_by_id.return_value = None
    with patch("iris.llm.llm_manager.LlmManager", return_value=manager):
        assert model_supports_logprobs("missing") is False


# ──────────────────────────────────────────────────────────────────────────
# openai_chat: request logprobs and surface them on the PyrisMessage
# ──────────────────────────────────────────────────────────────────────────
def _mock_openai_response(logprobs=None):
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
                logprobs=logprobs,
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


def _invoke_chat(model, response, **completion_kwargs):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = response
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: mock_client):
        message = model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return mock_client.chat.completions.create.call_args.kwargs, message


def test_logprobs_not_requested_by_default():
    model = _build_model()  # supports_logprobs defaults to True
    params, _ = _invoke_chat(model, _mock_openai_response())
    assert "logprobs" not in params


def test_logprobs_requested_when_opted_in_and_supported():
    model = _build_model()
    params, _ = _invoke_chat(model, _mock_openai_response(), logprobs=True)
    assert params["logprobs"] is True


def test_logprobs_dropped_when_model_does_not_support_them():
    model = _build_model(supports_logprobs=False)
    params, _ = _invoke_chat(model, _mock_openai_response(), logprobs=True)
    assert "logprobs" not in params


def test_token_logprobs_extracted_onto_message():
    model = _build_model()
    logprobs_payload = SimpleNamespace(
        content=[
            SimpleNamespace(token="ok", logprob=-0.1),
            SimpleNamespace(token="!", logprob=-0.3),
        ]
    )
    _, message = _invoke_chat(
        model, _mock_openai_response(logprobs_payload), logprobs=True
    )
    assert message.token_logprobs == [-0.1, -0.3]


def test_token_logprobs_none_when_absent():
    model = _build_model()
    _, message = _invoke_chat(model, _mock_openai_response())
    assert message.token_logprobs is None
