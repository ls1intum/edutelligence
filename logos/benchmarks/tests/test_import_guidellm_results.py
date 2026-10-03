"""Tests for the GuideLLM summary importer."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_IMPORTER_PATH = Path(__file__).resolve().parent.parent / "import_guidellm_results.py"
_spec = importlib.util.spec_from_file_location("guidellm_importer_under_test", _IMPORTER_PATH)
importer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = importer
_spec.loader.exec_module(importer)


def test_build_payloads_keeps_only_successful_benchmarks():
    report = {
        "metadata": {"version": 2, "guidellm_version": "0.7.0"},
        "config": {"profile": {"kind": "sweep"}},
        "benchmarks": [
            {
                "config": {"rate": 2},
                "end_time": 1_700_000_000,
                "metrics": {
                    "request_totals": {"successful": 10, "incomplete": 0, "errored": 0, "total": 10},
                    "time_to_first_token_ms": {"successful": {"p50": 120.0}},
                },
            },
            {
                "config": {"rate": 4},
                "metrics": {"request_totals": {"successful": 9, "incomplete": 0, "errored": 1, "total": 10}},
            },
        ],
    }

    payloads = importer.build_payloads(report, model_provider_id=7, dataset="openai/gsm8k")

    assert len(payloads) == 1
    assert payloads[0]["model_provider_id"] == 7
    assert payloads[0]["dataset"] == "openai/gsm8k"
    assert payloads[0]["sample_size"] == 10
    assert payloads[0]["configuration"]["tool"] == "guidellm"
    assert payloads[0]["configuration"]["metadata"]["guidellm_version"] == "0.7.0"
    assert payloads[0]["configuration"]["benchmark"] == {"rate": 2}
    assert payloads[0]["metrics"]["time_to_first_token_ms"]["successful"]["p50"] == 120.0
    assert payloads[0]["recorded_at"] == "2023-11-14T22:13:20+00:00"


def test_build_payloads_removes_secrets_from_configuration():
    report = {
        "config": {
            "spec": {
                "backend": {
                    "api_key": "provider-secret",
                    "extras": {"headers": {"authorization": "Bearer secret"}},
                }
            }
        },
        "benchmarks": [
            {
                "config": {"backend": {"token": "secret", "model": "Qwen/Qwen3-8B"}},
                "metrics": {
                    "request_totals": {
                        "successful": 1,
                        "incomplete": 0,
                        "errored": 0,
                        "total": 1,
                    }
                },
            }
        ],
    }

    payload = importer.build_payloads(report, 7, "openai/gsm8k")[0]

    assert "api_key" not in payload["configuration"]["scenario"]["spec"]["backend"]
    assert "authorization" not in payload["configuration"]["scenario"]["spec"]["backend"]["extras"]["headers"]
    assert "token" not in payload["configuration"]["benchmark"]["backend"]
    assert payload["configuration"]["benchmark"]["backend"]["model"] == "Qwen/Qwen3-8B"


def test_build_payloads_rejects_inconsistent_or_non_integer_totals():
    report = {
        "benchmarks": [
            {"metrics": {"request_totals": {"successful": 9, "incomplete": 0, "errored": 0, "total": 10}}},
            {"metrics": {"request_totals": {"successful": 10.0, "incomplete": 0, "errored": 0, "total": 10}}},
        ]
    }

    assert importer.build_payloads(report, 7, "openai/gsm8k") == []


def test_import_credentials_require_https_except_on_loopback():
    assert importer.credential_transport_is_secure("https://logos.example/import")
    assert importer.credential_transport_is_secure("http://localhost:18082/import")
    assert importer.credential_transport_is_secure("http://127.0.0.1:18082/import")
    assert not importer.credential_transport_is_secure("http://logos.example/import")


def test_loopback_import_disables_proxies_and_redirects(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = SimpleNamespace(status=200)
    opener = MagicMock()
    opener.open.return_value = response
    build_opener = MagicMock(return_value=opener)
    monkeypatch.setattr(importer.urllib.request, "build_opener", build_opener)

    importer.post_payload("http://localhost:18082/import", "token", {"sample_size": 1})

    handlers = build_opener.call_args.args
    assert any(isinstance(handler, importer.urllib.request.ProxyHandler) for handler in handlers)
    assert any(isinstance(handler, importer._RejectRedirects) for handler in handlers)
