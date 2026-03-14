"""Tests for memiris.llm.ollama_language_model.OllamaLanguageModel."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_ollama import ChatOllama

from memiris.llm.ollama_language_model import OllamaLanguageModel
from memiris.llm.retry_config import RetryConfig, set_retry_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ollama_response(content: str = "hello", model: str = "llama3") -> MagicMock:
    """Build a minimal Ollama chat-response-like mock."""
    message = MagicMock()
    message.role = "assistant"
    message.content = content
    message.name = None
    message.tool_calls = None

    resp = MagicMock()
    resp.model = model
    resp.created_at = None
    resp.done = True
    resp.total_duration = None
    resp.load_duration = None
    resp.prompt_eval_count = None
    resp.prompt_eval_duration = None
    resp.eval_count = None
    resp.eval_duration = None
    # make __dict__ work for WrappedChatResponse.from_ollama_response
    resp.__dict__.update(
        {
            "message": {
                "role": "assistant",
                "content": content,
                "name": None,
                "tool_calls": None,
            },
            "model": model,
            "created_at": None,
            "done": True,
        }
    )
    return resp


def _make_ollama_embed_response(
    embeddings: list[list[float]], model: str = "llama3"
) -> MagicMock:
    """Build a minimal Ollama embed-response-like mock."""
    resp = MagicMock()
    resp.__dict__.update({"embeddings": embeddings, "model": model})
    return resp


def _make_list_response(model_names: list[str]) -> MagicMock:
    """Build a minimal Ollama list/ps-response-like mock."""
    models = []
    for name in model_names:
        m = MagicMock()
        m.model = name
        models.append(m)
    resp = MagicMock()
    resp.get = lambda key, default=None: models if key == "models" else default
    return resp


def _make_langfuse_mock() -> MagicMock:
    """Return a langfuse client mock with a working context-manager generation."""
    generation = MagicMock()
    generation.__enter__ = MagicMock(return_value=generation)
    generation.__exit__ = MagicMock(return_value=False)
    lf = MagicMock()
    lf.start_as_current_generation.return_value = generation
    return lf


def _make_model(
    ollama_client: MagicMock,
    langfuse: MagicMock,
    model_name: str = "llama3",
    host: str = "http://localhost:11434",
    token: str | None = None,
) -> OllamaLanguageModel:
    """Construct an OllamaLanguageModel with patched dependencies."""
    with (
        patch("memiris.llm.ollama_language_model.Client", return_value=ollama_client),
        patch(
            "memiris.llm.ollama_language_model.langfuse.get_client",
            return_value=langfuse,
        ),
    ):
        return OllamaLanguageModel(model=model_name, host=host, token=token)


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


class TestOllamaLanguageModelConstruction:
    """Tests for OllamaLanguageModel.__init__ and basic properties."""

    def test_model_property(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        assert m.model == "llama3"

    def test_host_is_stored(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        assert m.host == "http://localhost:11434"

    def test_token_none_by_default(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        assert m.token is None

    def test_cookies_none_without_token(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        assert m._cookies is None  # pylint: disable=protected-access

    def test_cookies_set_with_token(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf, token="secret")
        assert m._cookies == {"token": "secret"}  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# chat()
# ---------------------------------------------------------------------------


class TestOllamaLanguageModelChat:
    """Tests for OllamaLanguageModel.chat()."""

    def test_basic_chat_returns_wrapped_response(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response("hi there")
        resp = m.chat([{"role": "user", "content": "hello"}])
        assert resp.message.content == "hi there"
        assert resp.message.role == "assistant"

    def test_chat_passes_model_and_messages(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        messages = [{"role": "user", "content": "ping"}]
        m.chat(messages)
        client.chat.assert_called_once()
        args, kwargs = client.chat.call_args
        assert args[0] == "llama3"
        assert kwargs["messages"] is messages

    def test_chat_passes_response_format(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        fmt = {"type": "object"}
        m.chat([{"role": "user", "content": "x"}], response_format=fmt)
        _, kwargs = client.chat.call_args
        assert kwargs["format"] is fmt

    def test_chat_passes_keep_alive(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        m.chat([], keep_alive="10m")
        _, kwargs = client.chat.call_args
        assert kwargs["keep_alive"] == "10m"

    def test_chat_passes_options(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        opts = {"temperature": 0.9}
        m.chat([], options=opts)
        _, kwargs = client.chat.call_args
        assert kwargs["options"] is opts

    def test_chat_think_set_for_gpt_oss_model(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf, model_name="gpt-oss-reasoning")
        client.chat.return_value = _make_ollama_response(model="gpt-oss-reasoning")
        m.chat([])
        _, kwargs = client.chat.call_args
        assert kwargs["think"] == "high"

    def test_chat_think_none_for_regular_model(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        m.chat([])
        _, kwargs = client.chat.call_args
        assert kwargs["think"] is None

    def test_chat_calls_langfuse_generation(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        m.chat([{"role": "user", "content": "hi"}])
        lf.start_as_current_generation.assert_called_once()
        call_kwargs = lf.start_as_current_generation.call_args.kwargs
        assert call_kwargs["name"] == "ollama-chat"
        assert call_kwargs["model"] == "llama3"


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestOllamaLanguageModelEmbed:
    """Tests for OllamaLanguageModel.embed()."""

    def test_embed_returns_wrapped_response(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        vec = [[0.1, 0.2, 0.3]]
        client.embed.return_value = _make_ollama_embed_response(vec)
        resp = m.embed("hello world")
        assert resp.embeddings == vec
        assert resp.model == "llama3"

    def test_embed_passes_model_and_text(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.embed.return_value = _make_ollama_embed_response([[0.0]])
        m.embed("some text")
        client.embed.assert_called_once_with("llama3", "some text")


# ---------------------------------------------------------------------------
# ensure_present() / is_loaded() / load() / unload()
# ---------------------------------------------------------------------------


class TestOllamaLanguageModelLifecycle:
    """Tests for model lifecycle methods."""

    def test_ensure_present_does_not_pull_when_model_present(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.list.return_value = _make_list_response(["llama3", "mistral"])
        m.ensure_present()
        client.pull.assert_not_called()

    def test_ensure_present_pulls_when_model_missing(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.list.return_value = _make_list_response(["mistral"])
        m.ensure_present()
        client.pull.assert_called_once_with("llama3")

    def test_is_loaded_true_when_model_in_ps(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.ps.return_value = _make_list_response(["llama3"])
        assert m.is_loaded() is True

    def test_is_loaded_false_when_model_not_in_ps(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.ps.return_value = _make_list_response(["mistral"])
        assert m.is_loaded() is False

    def test_load_calls_chat_with_keep_alive(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        m.load("5m")
        _, kwargs = client.chat.call_args
        assert kwargs["keep_alive"] == "5m"

    def test_unload_calls_chat_with_keep_alive_zero(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.return_value = _make_ollama_response()
        m.unload()
        _, kwargs = client.chat.call_args
        assert kwargs["keep_alive"] == 0


# ---------------------------------------------------------------------------
# langchain_client()
# ---------------------------------------------------------------------------


class TestOllamaLanguageModelLangchain:
    """Tests for OllamaLanguageModel.langchain_client()."""

    def test_langchain_client_returns_chat_ollama(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        lc = m.langchain_client()
        assert isinstance(lc, ChatOllama)

    def test_langchain_client_passes_model_and_host(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        lc = m.langchain_client()
        assert lc.model == "llama3"
        assert lc.base_url == "http://localhost:11434"

    def test_langchain_client_reasoning_set_for_gpt_oss(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf, model_name="gpt-oss-reasoning")
        lc = m.langchain_client()
        assert lc.reasoning == "high"

    def test_langchain_client_reasoning_none_for_regular(self) -> None:
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        lc = m.langchain_client()
        assert lc.reasoning is None


# ---------------------------------------------------------------------------
# Retry integration
# ---------------------------------------------------------------------------


class TestOllamaLanguageModelRetry:
    """Tests that call_with_retry is correctly applied to chat() and embed()."""

    def test_chat_retries_on_failure_then_succeeds(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        good = _make_ollama_response("ok")
        client.chat.side_effect = [RuntimeError("transient"), good]
        resp = m.chat([{"role": "user", "content": "hi"}])
        assert resp.message.content == "ok"
        assert client.chat.call_count == 2

    def test_chat_raises_after_all_attempts(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=2, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError, match="down"):
            m.chat([{"role": "user", "content": "hi"}])
        assert client.chat.call_count == 2

    def test_embed_retries_on_failure_then_succeeds(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=3, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        good = _make_ollama_embed_response([[0.5, 0.6]])
        client.embed.side_effect = [ConnectionError("timeout"), good]
        resp = m.embed("text")
        assert resp.embeddings == [[0.5, 0.6]]
        assert client.embed.call_count == 2

    def test_embed_raises_after_all_attempts(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=2, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.embed.side_effect = ConnectionError("gone")
        with pytest.raises(ConnectionError):
            m.embed("text")
        assert client.embed.call_count == 2

    def test_no_retry_when_max_attempts_is_one(self) -> None:
        set_retry_config(
            RetryConfig(max_attempts=1, initial_delay=0.0, backoff_factor=1.0)
        )
        client = MagicMock()
        lf = _make_langfuse_mock()
        m = _make_model(client, lf)
        client.chat.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError):
            m.chat([])
        client.chat.assert_called_once()
