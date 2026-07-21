import json
import runpy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from openai import APITimeoutError

from iris.qa.attestation import run_responses_attestation
from iris.qa.cost import ModelRate, SpendLedger
from iris.qa.deployment_verification import validate_deployment_verification

SCRIPT = Path(__file__).parents[1] / "qa" / "scripts" / "verify_azure_deployments.py"


def _arm_entry(deployment: str, model: str, version: str = "2026-03-17") -> dict:
    return {
        "name": deployment,
        "properties": {
            "model": {"format": "OpenAI", "name": model, "version": version},
            "provisioningState": "Succeeded",
        },
    }


def test_arm_listing_verifies_exact_underlying_models():
    verify = runpy.run_path(str(SCRIPT))["verify_deployments"]
    expected = {
        "gpt-5.4-mini": "mini-deployment",
        "gpt-5.5": "large-deployment",
        "gpt-5.4": "judge-deployment",
    }
    listing = [_arm_entry(deployment, model) for model, deployment in expected.items()]

    verified = verify(listing, expected)

    assert verified["gpt-5.5"]["deployment"] == "large-deployment"
    assert verified["gpt-5.4-mini"]["version"] == "2026-03-17"


def test_arm_listing_rejects_wrong_model_behind_deployment():
    verify = runpy.run_path(str(SCRIPT))["verify_deployments"]

    with pytest.raises(ValueError, match="expected 'OpenAI'/'gpt-5.5'"):
        verify(
            [_arm_entry("large-deployment", "gpt-5.4-mini")],
            {"gpt-5.5": "large-deployment"},
        )


def test_paid_run_rejects_stale_deployment_proof(tmp_path, monkeypatch):
    endpoint = "https://qa-resource.openai.azure.com"
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", endpoint)
    monkeypatch.setenv("IRIS_QA_AZURE_RESOURCE_GROUP", "qa-rg")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "qa-subscription")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    proof = {
        "version": 1,
        "verifiedAt": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "source": "Azure Resource Manager deployment listing",
        "subscriptionId": "qa-subscription",
        "endpoint": endpoint,
        "resourceGroup": "qa-rg",
        "accountName": "qa-resource",
        "deployments": {
            "gpt-5.4-mini": {
                "deployment": "mini",
                "model": "gpt-5.4-mini",
                "version": "1",
            },
            "gpt-5.5": {
                "deployment": "large",
                "model": "gpt-5.5",
                "version": "1",
            },
            "gpt-5.4": {
                "deployment": "judge",
                "model": "gpt-5.4",
                "version": "1",
            },
        },
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(ValueError, match="no more than one hour old"):
        validate_deployment_verification(path)


def test_paid_run_accepts_fresh_responses_api_attestation(tmp_path, monkeypatch):
    endpoint = "https://qa-resource.openai.azure.com"
    names = {
        "gpt-5.4-mini": "mini",
        "gpt-5.5": "large",
        "gpt-5.4": "judge",
    }
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", endpoint)
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", names["gpt-5.4-mini"])
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", names["gpt-5.5"])
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", names["gpt-5.4"])
    proof = {
        "version": 1,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Azure Responses API model attestation",
        "endpoint": endpoint,
        "accountName": "qa-resource",
        "deployments": {
            model: {
                "deployment": deployment,
                "model": model,
                "version": "provider-reported",
                "responseStatus": "completed",
                "inputTokens": 10,
                "outputTokens": 5,
            }
            for model, deployment in names.items()
        },
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof), encoding="utf-8")

    assert validate_deployment_verification(path) == proof


def test_mini_only_run_accepts_proof_without_unselected_gpt_55(tmp_path, monkeypatch):
    endpoint = "https://qa-resource.openai.azure.com"
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", endpoint)
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    monkeypatch.delenv("IRIS_QA_GPT_55_DEPLOYMENT", raising=False)
    proof = {
        "version": 1,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Azure Responses API model attestation",
        "endpoint": endpoint,
        "accountName": "qa-resource",
        "deployments": {
            model: {
                "deployment": deployment,
                "model": model,
                "version": "provider-reported",
                "responseStatus": "completed",
                "inputTokens": 10,
                "outputTokens": 5,
            }
            for model, deployment in {
                "gpt-5.4-mini": "mini",
                "gpt-5.4": "judge",
            }.items()
        },
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof), encoding="utf-8")

    assert (
        validate_deployment_verification(path, candidate_models=("gpt-5.4-mini",))
        == proof
    )


def test_timed_out_responses_attestation_reserves_probe_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_QA_AZURE_AUTH_MODE", "api_key")
    monkeypatch.setenv("IRIS_QA_AZURE_ENDPOINT", "https://qa.openai.azure.com")
    monkeypatch.setenv("IRIS_QA_AZURE_API_KEY", "local-test-key")
    monkeypatch.setenv("IRIS_QA_GPT_54_MINI_DEPLOYMENT", "mini")
    monkeypatch.setenv("IRIS_QA_GPT_55_DEPLOYMENT", "large")
    monkeypatch.setenv("IRIS_QA_JUDGE_DEPLOYMENT", "judge")
    mini = ModelRate("gpt-5.4-mini", Decimal(1), Decimal(1))
    rate_card = SimpleNamespace(
        candidates=(mini, ModelRate("gpt-5.5", Decimal(1), Decimal(1))),
        judge=ModelRate("gpt-5.4", Decimal(1), Decimal(1)),
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=Mock(
                side_effect=APITimeoutError(
                    request=httpx.Request("POST", "https://qa.openai.azure.com")
                )
            )
        )
    )
    ledger = tmp_path / "ledger.jsonl"

    with (
        patch("iris.qa.attestation.OpenAI", return_value=client),
        pytest.raises(APITimeoutError),
    ):
        run_responses_attestation(
            rate_card=rate_card,
            ledger_path=ledger,
            hard_limit=Decimal(1),
            max_cost=Decimal(1),
            output=tmp_path / "proof.json",
        )

    records = SpendLedger(ledger).records()
    assert len(records) == 1
    assert records[0].reservation is True
    assert Decimal(records[0].cost_usd) == mini.cost(256, 128)
