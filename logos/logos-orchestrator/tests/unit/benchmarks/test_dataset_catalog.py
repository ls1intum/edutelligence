import httpx
import pytest
from fastapi import HTTPException

from logos.benchmarks import huggingface_datasets as hf


async def test_catalog_pages_use_fixed_hub_url_and_return_next_cursor(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=[{"id": "org/public"}, {"id": "org/gated", "gated": True}, {"id": "org/private", "private": True}],
                headers={"Link": '<https://huggingface.co/api/datasets?cursor=page%2B2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": "org/second"}])

    client = httpx.AsyncClient
    monkeypatch.setattr(
        hf.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs)
    )
    first = await hf.search_datasets("")
    assert first == {"datasets": [{"id": "org/public"}], "next_cursor": "page+2"}
    second = await hf.search_datasets("", first["next_cursor"])
    assert second == {"datasets": [{"id": "org/second"}], "next_cursor": None}
    assert requests[1].url.host == "huggingface.co"
    assert requests[1].url.path == "/api/datasets"
    assert requests[1].url.params["cursor"] == "page+2"
    assert requests[0].url.params["limit"] == "20"


async def test_catalog_error_is_reported_as_retryable(monkeypatch):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        hf.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs),
    )
    with pytest.raises(HTTPException) as error:
        await hf.search_datasets("math")
    assert error.value.status_code == 503
