import pytest

from logos.responses import proxy_behaviour


class DummyDB:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_provider(self, provider):
        # provider can be dict or id
        if isinstance(provider, dict):
            return provider
        return {"id": provider, "name": "azure", "base_url": "https://example.com"}


def test_proxy_behaviour_selects_azure_with_required_headers(monkeypatch):
    providers = [{"id": 1, "name": "azure", "base_url": "https://example.com"}]
    headers = {"Authorization": "Bearer test", "Content-Type": "application/json"}

    monkeypatch.setattr("logos.responses.DBManager", DummyDB)
    monkeypatch.setattr(
        "logos.responses.parse_provider_config",
        lambda name: {
            "required_headers": ["Authorization"],
            "forward_url": "{base_url}/{path}",
            "auth": {"header": "Authorization", "format": "{Authorization}"},
        },
    )
    out = proxy_behaviour(headers, providers, path="chat/completions")

    assert isinstance(out, tuple) and len(out) == 3
    proxy_headers, forward_url, provider_id = out
    assert proxy_headers["Authorization"] == "Bearer test"
    assert forward_url.startswith("https://example.com")
    assert provider_id == 1


def test_proxy_behaviour_errors_when_no_provider(monkeypatch):
    providers = [{"id": 2, "name": "custom", "base_url": "https://custom"}]
    headers = {"Authorization": "Bearer test"}

    monkeypatch.setattr("logos.responses.DBManager", DummyDB)
    err, code = proxy_behaviour(headers, providers, path="chat/completions")
    assert "error" in err
    assert code == 500
