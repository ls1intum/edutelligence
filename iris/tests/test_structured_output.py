"""Schema-enforced JSON output on every provider path."""

from types import SimpleNamespace
from typing import Literal, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.llm.structured_output import (  # noqa: E402
    StructuredOutputError,
    parse_structured_output,
    strict_json_schema,
)


class _Inner(BaseModel):
    label: str


class _Answer(BaseModel):
    decision: Literal["keep", "update"]
    title: Optional[str] = None
    items: list[_Inner] = []


def _user():
    return PyrisMessage(
        sender=IrisMessageRole.USER, contents=[TextMessageContentDTO(textContent="q")]
    )


def test_strict_schema_requires_every_property_and_forbids_extras():
    schema = strict_json_schema(_Answer)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["decision", "title", "items"]
    inner = schema["$defs"]["_Inner"]
    assert inner["additionalProperties"] is False and inner["required"] == ["label"]
    assert "default" not in str(schema) and "title" not in schema


def test_parse_accepts_a_code_fence_and_rejects_wrong_shapes():
    assert (
        parse_structured_output(_Answer, '```json\n{"decision": "keep"}\n```').decision
        == "keep"
    )
    with pytest.raises(StructuredOutputError):
        parse_structured_output(_Answer, "KEEP")


def _model(**fields):
    return DirectOpenAIChatModel(
        id="m",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
        **fields,
    )


def _completion(text):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant", content=text, tool_calls=None, refusal=None
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def test_chat_completions_sends_a_strict_json_schema():
    client = MagicMock()
    client.chat.completions.create.return_value = _completion('{"decision":"keep"}')

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        _model().chat([_user()], CompletionArguments(response_schema=_Answer), None)

    response_format = client.chat.completions.create.call_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["name"] == "_Answer"


def test_endpoint_without_schema_support_falls_back_to_json_mode():
    client = MagicMock()
    client.chat.completions.create.return_value = _completion('{"decision":"keep"}')

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        _model(supports_structured_output=False).chat(
            [_user()], CompletionArguments(response_schema=_Answer), None
        )

    response_format = client.chat.completions.create.call_args.kwargs["response_format"]
    assert dict(response_format) == {"type": "json_object"}


def test_responses_api_sends_the_schema_as_text_format():
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed",
        output=[],
        output_text='{"decision":"keep"}',
        error=None,
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )

    with patch.object(DirectOpenAIChatModel, "get_client", lambda self: client):
        _model(use_responses_api=True).chat(
            [_user()], CompletionArguments(response_schema=_Answer), None
        )

    text_format = client.responses.create.call_args.kwargs["text"]["format"]
    assert text_format["type"] == "json_schema" and text_format["strict"] is True
