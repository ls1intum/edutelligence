"""Executor streaming payload preparation.

``stream_options.include_usage`` is Chat-Completions-only: the Responses API
rejects it as an unknown parameter (usage always arrives in the terminal
``response.completed`` event), so it must not be injected for ``/responses``
upstreams.
"""

from logos.pipeline.executor import Executor

AZURE_RESPONSES = "https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview"
OPENAI_RESPONSES = "https://api.openai.com/v1/responses"
OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


def test_chat_completions_gets_stream_options():
    payload = Executor._streaming_payload(OPENAI_CHAT, {"model": "gpt-4o"})
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_openai_responses_url_skips_stream_options():
    payload = Executor._streaming_payload(OPENAI_RESPONSES, {"model": "gpt-5.1", "input": "hi"})
    assert payload["stream"] is True
    assert "stream_options" not in payload


def test_azure_responses_url_skips_stream_options():
    payload = Executor._streaming_payload(AZURE_RESPONSES, {"model": "gpt-4o", "input": "hi"})
    assert payload["stream"] is True
    assert "stream_options" not in payload


def test_is_responses_url_ignores_query_and_trailing_slash():
    assert Executor._is_responses_url(AZURE_RESPONSES)
    assert Executor._is_responses_url("https://api.openai.com/v1/responses/")
    assert not Executor._is_responses_url(OPENAI_CHAT)
    assert not Executor._is_responses_url("")
