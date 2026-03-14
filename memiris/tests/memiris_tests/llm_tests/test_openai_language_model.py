"""Tests for memiris.llm.openai_language_model.OpenAiLanguageModel."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice

from memiris.llm.openai_language_model import OpenAiLanguageModel
from memiris.llm.retry_config import RetryConfig, set_retry_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completion(content: str, model: str = "gpt-4o") -> MagicMock:
    """Build a minimal ChatCompletion-like mock."""
    message = MagicMock()
    message.role = "assistant"
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message

    completion = MagicMock()
    completion.choices = [choice]
    completion.model = model
    return completion


def _make_real_completion(content: str, model: str = "gpt-4o") -> ChatCompletion:
    """Build a real ChatCompletion so that model_copy() works correctly."""
    msg = ChatCompletionMessage(role="assistant", content=content)
    choice = Choice(index=0, message=msg, finish_reason="stop")
    return ChatCompletion(
        id="chatcmpl-test",
        choices=[choice],
        created=int(time.time()),
        model=model,
        object="chat.completion",
    )


def _make_embedding_response(
    vector: list[float], model: str = "text-embedding-3-small"
) -> MagicMock:
    """Build a minimal embedding response mock."""
    embedding = MagicMock()
    embedding.embedding = vector

    resp = MagicMock()
    resp.data = [embedding]
    resp.model = model
    return resp


def _make_model(
    openai_client: MagicMock,
    model_name: str = "gpt-4o",
    api_key: str = "test-key",
) -> OpenAiLanguageModel:
    """Construct an OpenAiLanguageModel with a patched OpenAI client."""
    with patch("memiris.llm.openai_language_model.OpenAI", return_value=openai_client):
        return OpenAiLanguageModel(model=model_name, api_key=api_key)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_retry_config() -> Any:
    """Restore default retry config after every test."""
    yield
    set_retry_config(RetryConfig())


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestOpenAiLanguageModelConstruction:
    """Tests for OpenAiLanguageModel.__init__ and basic properties."""

    def test_model_property(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        assert m.model == "gpt-4o"

    def test_is_loaded_always_true(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        assert m.is_loaded() is True

    def test_ensure_present_is_noop(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        m.ensure_present()  # must not raise

    def test_load_is_noop(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        m.load()  # must not raise

    def test_unload_is_noop(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        m.unload()  # must not raise

    def test_azure_raises_without_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Azure endpoint"):
            OpenAiLanguageModel(model="gpt-4o", azure=True, api_key="k")

    def test_azure_construction_succeeds(self) -> None:
        with patch("memiris.llm.openai_language_model.AzureOpenAI"):
            m = OpenAiLanguageModel(
                model="gpt-4o",
                azure=True,
                api_key="k",
                azure_endpoint="https://example.openai.azure.com/",
            )
        assert m.model == "gpt-4o"


# ---------------------------------------------------------------------------
# chat()
# ---------------------------------------------------------------------------


class TestOpenAiLanguageModelChat:
    """Tests for OpenAiLanguageModel.chat()."""

    def test_basic_chat_returns_wrapped_response(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        client.chat.completions.create.return_value = _make_completion("Hello!")
        resp = m.chat([{"role": "user", "content": "Hi"}])
        assert resp.message.content == "Hello!"
        assert resp.message.role == "assistant"

    def test_chat_passes_model_and_messages(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        client.chat.completions.create.return_value = _make_completion("ok")
        m.chat([{"role": "user", "content": "ping"}])
        call_kwargs = client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o"
        messages = call_kwargs.kwargs["messages"]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "ping"

    def test_chat_with_object_message(self) -> None:
        """Messages with .role/.content attributes are normalized."""
        client = MagicMock()
        m = _make_model(client)
        msg = MagicMock()
        msg.role = "user"
        msg.content = "hello"
        client.chat.completions.create.return_value = _make_completion("hi")
        resp = m.chat([msg])
        assert resp.message.content == "hi"

    def test_chat_passes_options_as_payload(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        client.chat.completions.create.return_value = _make_completion("ok")
        m.chat([{"role": "user", "content": "x"}], options={"temperature": 0.7})
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7

    def test_chat_with_response_format_object_schema(self) -> None:
        """An object-typed JSON schema is forwarded as structured output."""
        client = MagicMock()
        m = _make_model(client)
        schema = {
            "name": "my_schema",
            "schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        }
        client.chat.completions.create.return_value = _make_completion(
            json.dumps({"value": "42"})
        )
        resp = m.chat([{"role": "user", "content": "go"}], response_format=schema)
        assert resp.message.content == json.dumps({"value": "42"})

    def test_chat_wraps_non_object_schema_and_unwraps(self) -> None:
        """Non-object (array) root schemas are wrapped/unwrapped transparently."""
        client = MagicMock()
        m = _make_model(client)
        schema = {
            "name": "items",
            "schema": {"type": "array", "items": {"type": "string"}},
        }
        inner = ["a", "b"]
        client.chat.completions.create.return_value = _make_real_completion(
            json.dumps({"result": inner})
        )
        resp = m.chat([{"role": "user", "content": "list"}], response_format=schema)
        assert json.loads(resp.message.content) == inner  # type: ignore[arg-type]

    def test_chat_temperature_omitted_for_gpt5(self) -> None:
        """Temperature is silently dropped for gpt-5* models."""
        client = MagicMock()
        with patch("memiris.llm.openai_language_model.OpenAI", return_value=client):
            m = OpenAiLanguageModel(model="gpt-5", api_key="k")
        client.chat.completions.create.return_value = _make_completion(
            "ok", model="gpt-5"
        )
        m.chat([{"role": "user", "content": "x"}], options={"temperature": 0.5})
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "temperature" not in call_kwargs


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestOpenAiLanguageModelEmbed:
    """Tests for OpenAiLanguageModel.embed()."""

    def test_embed_returns_wrapped_response(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        vec = [0.1, 0.2, 0.3]
        client.embeddings.create.return_value = _make_embedding_response(vec)
        resp = m.embed("hello world")
        assert resp.embeddings == [vec]
        assert resp.model == "text-embedding-3-small"

    def test_embed_passes_text_and_model(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        client.embeddings.create.return_value = _make_embedding_response([0.0])
        m.embed("some text")
        call_kwargs = client.embeddings.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["input"] == "some text"


# ---------------------------------------------------------------------------
# Retry integration
# ---------------------------------------------------------------------------


class TestOpenAiLanguageModelRetry:
    """Tests that call_with_retry is correctly applied to chat() and embed()."""

    def test_chat_retries_on_failure_then_succeeds(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        m = _make_model(client)
        completion = _make_completion("ok")
        client.chat.completions.create.side_effect = [
            RuntimeError("transient"),
            completion,
        ]
        resp = m.chat([{"role": "user", "content": "hi"}])
        assert resp.message.content == "ok"
        assert client.chat.completions.create.call_count == 2

    def test_chat_raises_after_all_attempts(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=2, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        m = _make_model(client)
        client.chat.completions.create.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError, match="down"):
            m.chat([{"role": "user", "content": "hi"}])
        assert client.chat.completions.create.call_count == 2

    def test_embed_retries_on_failure_then_succeeds(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        m = _make_model(client)
        vec = [0.5, 0.6]
        client.embeddings.create.side_effect = [
            ConnectionError("timeout"),
            _make_embedding_response(vec),
        ]
        resp = m.embed("text")
        assert resp.embeddings == [vec]
        assert client.embeddings.create.call_count == 2

    def test_embed_raises_after_all_attempts(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=2, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        m = _make_model(client)
        client.embeddings.create.side_effect = ConnectionError("gone")
        with pytest.raises(ConnectionError):
            m.embed("text")
        assert client.embeddings.create.call_count == 2

    def test_no_retry_when_max_attempts_is_one(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=1, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        m = _make_model(client)
        client.chat.completions.create.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError):
            m.chat([{"role": "user", "content": "x"}])
        client.chat.completions.create.assert_called_once()


# ---------------------------------------------------------------------------
# langchain_client()
# ---------------------------------------------------------------------------


class TestOpenAiLanguageModelLangchain:
    """Tests for OpenAiLanguageModel.langchain_client()."""

    def test_langchain_client_returns_chat_openai(self) -> None:
        client = MagicMock()
        m = _make_model(client)
        lc = m.langchain_client()
        assert isinstance(lc, ChatOpenAI)

    def test_langchain_client_azure_returns_azure_chat_openai(self) -> None:

        with patch("memiris.llm.openai_language_model.AzureOpenAI"):
            m = OpenAiLanguageModel(
                model="gpt-4o",
                azure=True,
                api_key="k",
                azure_endpoint="https://example.openai.azure.com/",
            )
        lc = m.langchain_client()
        assert isinstance(lc, AzureChatOpenAI)
