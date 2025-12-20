"""
Pytest configuration for scheduling_data tests.
Registers custom CLI options for test parameters and provides fixtures.
"""

import pytest
import requests


def pytest_addoption(parser):
    """Register custom CLI options for test configuration."""
    # SSH configuration
    parser.addoption(
        "--ssh-host",
        action="store",
        default=None,
        help="SSH hostname for live Ollama tests"
    )
    parser.addoption(
        "--ssh-user",
        action="store",
        default=None,
        help="SSH username for live Ollama tests"
    )
    parser.addoption(
        "--ssh-key-path",
        action="store",
        default=None,
        help="Path to SSH private key"
    )
    parser.addoption(
        "--ssh-remote-port",
        action="store",
        default="11434",
        help="Remote Ollama port (default: 11434)"
    )

    # Model IDs
    parser.addoption(
        "--ollama-live-model-id",
        action="store",
        default=None,
        help="Ollama model ID for DB-driven live tests"
    )
    parser.addoption(
        "--azure-model-id",
        action="store",
        default="12",
        help="Azure model ID for tests (default: 12)"
    )
    parser.addoption(
        "--azure-live-model-id",
        action="store",
        default=None,
        help="Azure model ID for DB-driven live tests"
    )


@pytest.fixture
def ssh_config(request):
    """Return SSH config dict or None if incomplete."""
    host = request.config.getoption("--ssh-host")
    user = request.config.getoption("--ssh-user")
    key_path = request.config.getoption("--ssh-key-path")
    remote_port = request.config.getoption("--ssh-remote-port")

    if not (host and user and key_path):
        return None

    try:
        remote_port_int = int(remote_port)
    except ValueError:
        pytest.skip(f"Invalid --ssh-remote-port: {remote_port}")
        return None

    return {
        "ssh_host": host,
        "ssh_user": user,
        "ssh_port": 22,
        "ssh_key_path": key_path,
        "ssh_remote_ollama_port": remote_port_int,
    }


@pytest.fixture
def ollama_live_model_id(request):
    """Return Ollama live model ID or None."""
    model_id = request.config.getoption("--ollama-live-model-id")
    if not model_id:
        return None
    if not model_id.isdigit():
        pytest.skip(f"Invalid --ollama-live-model-id: {model_id}")
        return None
    return int(model_id)


@pytest.fixture
def azure_model_id(request):
    """Return Azure model ID (has default of 12)."""
    model_id = request.config.getoption("--azure-model-id")
    if not model_id or not model_id.isdigit():
        pytest.skip(f"Invalid --azure-model-id: {model_id}")
        return None
    return int(model_id)


@pytest.fixture
def azure_live_model_id(request):
    """Return Azure live model ID or None."""
    model_id = request.config.getoption("--azure-live-model-id")
    if not model_id:
        return None
    if not model_id.isdigit():
        pytest.skip(f"Invalid --azure-live-model-id: {model_id}")
        return None
    return int(model_id)


@pytest.fixture(autouse=True, scope="function")
def enable_ollama_http(monkeypatch):
    """
    Re-enable Ollama /api/ps polling so tests can supply mocked responses.

    Production code disables HTTP polling; this forces the provider to call
    requests.get (which tests patch) and use the returned JSON payload.
    """

    def _fetch_ps_via_http(self):
        if not self.base_url:
            return None
        try:
            resp = requests.get(f"{self.base_url}/api/ps", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            return None
        return None

    monkeypatch.setattr(
        "logos.sdi.providers.ollama_provider.OllamaDataProvider._fetch_ps_via_http",
        _fetch_ps_via_http,
    )


@pytest.fixture(autouse=True, scope="function")
def disable_ollama_db(monkeypatch):
    """
    Disable provider DB lookups to keep tests fully offline.
    """

    def _no_config(self):
        return {}

    monkeypatch.setattr(
        "logos.sdi.providers.ollama_provider.OllamaDataProvider._load_provider_config",
        _no_config,
    )
