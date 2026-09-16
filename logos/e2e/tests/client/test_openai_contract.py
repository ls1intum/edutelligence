"""Client tier: what an application talking to Logos actually experiences.

These go through the real ``openai`` SDK rather than raw HTTP. The SDK's parser
is the contract users depend on — a response that is valid JSON but shaped
slightly wrong still breaks every client, and a hand-rolled httpx call would not
notice.
"""

from __future__ import annotations

import openai
import pytest

pytestmark = pytest.mark.stack


@pytest.fixture
def client(orchestrator_url, developer_key) -> openai.OpenAI:
    return openai.OpenAI(base_url=f"{orchestrator_url}/v1", api_key=developer_key, max_retries=0)


def test_model_listing_is_a_valid_openai_response(client):
    """Clients discover what they can call here; it must parse even when empty.

    A fresh stack has no models attached to its providers yet, so the assertion
    is on the envelope, not on contents — this is the call every SDK makes first.
    """
    models = client.models.list()
    assert models.object == "list"
    assert isinstance(models.data, list)


def test_unknown_model_is_a_structured_error_not_a_stack_trace(client):
    """The failure a client hits most often has to be actionable.

    A 500 here would tell an application nothing about whether to retry, fall
    back, or fix its configuration.
    """
    with pytest.raises(openai.APIStatusError) as caught:
        client.chat.completions.create(
            model="definitely-not-a-real-model",
            messages=[{"role": "user", "content": "hello"}],
        )

    assert caught.value.status_code in (
        400,
        404,
        422,
    ), f"unknown model returned HTTP {caught.value.status_code} — a client cannot act on that"


def test_missing_credentials_are_rejected(orchestrator_url):
    anonymous = openai.OpenAI(base_url=f"{orchestrator_url}/v1", api_key="not-a-key", max_retries=0)

    with pytest.raises(openai.APIStatusError) as caught:
        anonymous.models.list()

    assert caught.value.status_code in (401, 403)


def test_developer_key_cannot_reach_admin_endpoints(orchestrator_url, developer_key):
    """Role separation must hold at the edge, not only in the UI."""
    import httpx

    response = httpx.post(
        f"{orchestrator_url}/logosdb/providers/logosnode/status",
        json={"logos_key": developer_key, "provider_id": 1},
        timeout=30.0,
    )

    assert response.status_code == 403, f"a developer key read node status (HTTP {response.status_code})"
