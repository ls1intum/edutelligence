from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Bootstrap the iris package in the order the pipelines use (see
# test_openai_chat_reasoning_effort.py for the circular-import background).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    LATE_SYSTEM_MESSAGE_PREFIX,
    DirectOpenAIChatModel,
    keep_system_messages_leading,
)

QWEN_THINKING = {"chat_template_kwargs": {"enable_thinking": True}}


def _mock_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant", content="ok", tool_calls=None, refusal=None
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _build_model(**overrides):
    base = {
        "id": "qwen",
        "type": "openai_chat",
        "model": "Qwen/Qwen3.8-27B",
        "api_key": "sk-test",  # pragma: allowlist secret
    }
    base.update(overrides)
    return DirectOpenAIChatModel(**base)


def _chat_params(model, **completion_kwargs):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response()
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        model.chat([], CompletionArguments(**completion_kwargs), tools=None)
    return client.chat.completions.create.call_args.kwargs


def _streamed_chat_params(model):
    client = MagicMock()
    client.chat.completions.create.return_value = iter([])
    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        model.chat(
            [], CompletionArguments(stream_handler=lambda _delta: None), tools=None
        )
    return client.chat.completions.create.call_args.kwargs


def test_extra_body_is_omitted_by_default():
    assert "extra_body" not in _chat_params(_build_model())


def test_extra_body_is_sent_with_chat_completions():
    params = _chat_params(
        _build_model(
            extra_body=QWEN_THINKING,
            supports_reasoning_effort=True,
            reasoning_effort="medium",
            reasoning_effort_values=["low", "medium", "xhigh"],
        )
    )
    assert params["extra_body"] == QWEN_THINKING
    assert params["reasoning_effort"] == "medium"


def test_extra_body_is_sent_with_streamed_chat_completions():
    params = _streamed_chat_params(_build_model(extra_body=QWEN_THINKING))
    assert params["stream"] is True
    assert params["extra_body"] == QWEN_THINKING


def test_extra_body_is_copied_per_request():
    model = _build_model(extra_body=QWEN_THINKING)
    params = _chat_params(model)
    params["extra_body"]["chat_template_kwargs"]["enable_thinking"] = False
    assert model.extra_body == QWEN_THINKING


def test_extra_body_is_sent_with_responses_api():
    model = _build_model(extra_body={"metadata_flag": True}, use_responses_api=True)
    params = model._create_responses_params(  # pylint: disable=protected-access
        [], CompletionArguments(), tools=None
    )
    assert params["extra_body"] == {"metadata_flag": True}


def test_out_of_scale_effort_is_clamped_to_a_thinking_level():
    # Qwen3.8 accepts only low/medium/xhigh; pipelines may still ask for
    # "none" or "high", which must map onto a level the template accepts.
    model = _build_model(
        extra_body=QWEN_THINKING,
        supports_reasoning_effort=True,
        reasoning_effort="medium",
        reasoning_effort_values=["low", "medium", "xhigh"],
    )
    assert _chat_params(model, reasoning_effort="none")["reasoning_effort"] == "low"
    assert _chat_params(model, reasoning_effort="high")["reasoning_effort"] in {
        "medium",
        "xhigh",
    }


def _text(text):
    return [{"type": "text", "text": text}]


def test_late_system_messages_become_marked_user_messages():
    messages = [
        {"role": "system", "content": _text("You are Iris.")},
        {"role": "system", "content": _text("Course context.")},
        {"role": "user", "content": _text("What is a stack?")},
        {"role": "assistant", "content": _text("A LIFO structure.")},
        {"role": "system", "content": _text("[context_switch] Exercise 3")},
        {"role": "user", "content": _text("And a queue?")},
    ]
    rewritten = keep_system_messages_leading(messages)

    assert [m["role"] for m in rewritten] == [
        "system",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert rewritten[0]["content"] == _text("You are Iris.") + _text("Course context.")
    assert rewritten[3]["content"] == _text(LATE_SYSTEM_MESSAGE_PREFIX) + _text(
        "[context_switch] Exercise 3"
    )
    # The input list is not mutated.
    assert messages[4]["role"] == "system"


def test_leading_system_rewrite_is_opt_in():
    def msg(role, text):
        return PyrisMessage(
            sender=role, contents=[TextMessageContentDTO(text_content=text)]
        )

    history = [
        msg(IrisMessageRole.SYSTEM, "You are Iris."),
        msg(IrisMessageRole.USER, "Hi"),
        msg(IrisMessageRole.SYSTEM, "[context_switch] Exercise 3"),
    ]

    def roles(model):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_response()
        with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
            model.chat(history, CompletionArguments(), tools=None)
        return [
            m["role"]
            for m in client.chat.completions.create.call_args.kwargs["messages"]
        ]

    assert roles(_build_model()) == ["system", "user", "system"]
    assert roles(_build_model(leading_system_message_only=True)) == [
        "system",
        "user",
        "user",
    ]


def test_reasoning_token_allowance_extends_pipeline_budgets():
    model = _build_model(reasoning_token_allowance=4096)
    assert _chat_params(model, max_tokens=30)["max_completion_tokens"] == 4126
    assert "max_completion_tokens" not in _chat_params(model)
    responses_model = _build_model(
        reasoning_token_allowance=100, use_responses_api=True
    )
    params = (
        responses_model._create_responses_params(  # pylint: disable=protected-access
            [], CompletionArguments(max_tokens=30), tools=None
        )
    )
    assert params["max_output_tokens"] == 130


def test_reasoning_token_allowance_defaults_to_unchanged_budgets():
    assert _chat_params(_build_model(), max_tokens=30)["max_completion_tokens"] == 30
