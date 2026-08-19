# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from langchain_core.tools import tool

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisAIMessage, PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments
from iris.llm.external.google_gemini import GoogleGeminiChatModel
from iris.llm.llm_manager import LlmList


def _build_model(**overrides):
    base = {
        "id": "gemini-test",
        "type": "google_gemini",
        "model": "gemini-test",
        "api_key": "test-key",  # pragma: allowlist secret
    }
    base.update(overrides)
    return GoogleGeminiChatModel(**base)


def _gemini_response(*, parts=None, finish_reason="STOP"):
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": parts or [{"text": "ok"}],
                },
                "finishReason": finish_reason,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 2,
        },
    }


def _http_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            "gemini error",
            response=SimpleNamespace(status_code=status_code),
        )
    return response


@tool("lookup")
def _lookup(query: str) -> str:
    """Lookup data."""
    return query


def test_llm_list_accepts_google_gemini_type():
    llms = LlmList(
        llms=[
            {
                "id": "gemini",
                "type": "google_gemini",
                "model": "gemini-2.5-flash",
                "api_key": "test-key",  # pragma: allowlist secret
            }
        ]
    )

    assert isinstance(llms.llms[0], GoogleGeminiChatModel)


def test_gemini_payload_maps_messages_config_and_tools():
    model = _build_model(
        generation_config={"topP": 0.8},
        tool_config={"functionCallingConfig": {"mode": "auto"}},
    )
    messages = [
        PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(textContent="Be concise.")],
        ),
        PyrisMessage(
            sender=IrisMessageRole.USER,
            contents=[
                TextMessageContentDTO(textContent="Describe this."),
                ImageMessageContentDTO(pdfFile="base64-image"),
            ],
        ),
    ]

    payload = model._create_payload(
        messages,
        CompletionArguments(
            temperature=0.2,
            max_tokens=42,
            stop=["END"],
            response_format="JSON",
        ),
        [_lookup],
    )

    assert payload["systemInstruction"] == {"parts": [{"text": "Be concise."}]}
    assert payload["contents"] == [
        {
            "role": "user",
            "parts": [
                {"text": "Describe this."},
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": "base64-image",
                    }
                },
            ],
        }
    ]
    assert payload["generationConfig"] == {
        "topP": 0.8,
        "temperature": 0.2,
        "maxOutputTokens": 42,
        "stopSequences": ["END"],
        "responseMimeType": "application/json",
    }
    assert payload["toolConfig"] == {"functionCallingConfig": {"mode": "auto"}}
    assert payload["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "lookup",
                    "description": "Lookup data.",
                    "parameters": {
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "type": "object",
                    },
                }
            ]
        }
    ]


def test_gemini_chat_posts_payload_and_returns_iris_message():
    model = _build_model()
    response = _http_response(_gemini_response(parts=[{"text": "hello"}]))
    model._session.post = MagicMock(return_value=response)

    result = model.chat(
        [
            PyrisMessage(
                sender=IrisMessageRole.USER,
                contents=[TextMessageContentDTO(textContent="hi")],
            )
        ],
        CompletionArguments(),
        tools=None,
    )

    model._session.post.assert_called_once()
    assert (
        model._session.post.call_args.args[0]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    )
    assert model._session.post.call_args.kwargs["json"] == {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}]
    }
    assert result.sender == IrisMessageRole.ASSISTANT
    assert result.contents[0].text_content == "hello"
    assert result.token_usage.model_info == "gemini-test"
    assert result.token_usage.num_input_tokens == 3
    assert result.token_usage.num_output_tokens == 2


def test_gemini_function_call_returns_pyris_ai_message():
    model = _build_model()
    model._session.post = MagicMock(
        return_value=_http_response(
            _gemini_response(
                parts=[
                    {
                        "functionCall": {
                            "id": "call-1",
                            "name": "lookup",
                            "args": {"query": "iris"},
                        }
                    }
                ],
                finish_reason="STOP",
            )
        )
    )

    result = model.chat([], CompletionArguments(), tools=None)

    assert isinstance(result, PyrisAIMessage)
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].function.name == "lookup"
    assert result.tool_calls[0].function.arguments == {"query": "iris"}


def test_gemini_retries_retryable_http_status_until_success():
    model = _build_model()
    model._session.post = MagicMock(
        side_effect=[
            _http_response({}, status_code=429),
            _http_response(_gemini_response(parts=[{"text": "ok"}])),
        ]
    )

    with patch("time.sleep") as sleep:
        result = model.chat([], CompletionArguments(), tools=None)

    assert result.contents[0].text_content == "ok"
    assert model._session.post.call_count == 2
    sleep.assert_called_once()
