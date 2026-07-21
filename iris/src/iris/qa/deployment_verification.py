from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_DEPLOYMENTS = {
    "gpt-5.4-mini": "IRIS_QA_GPT_54_MINI_DEPLOYMENT",
    "gpt-5.5": "IRIS_QA_GPT_55_DEPLOYMENT",
    "gpt-5.4": "IRIS_QA_JUDGE_DEPLOYMENT",
}


def validate_deployment_verification(
    path: Path,
    candidate_models: Sequence[str] = ("gpt-5.4-mini", "gpt-5.5"),
) -> dict:
    """Validate a fresh ARM proof against the exact paid-run environment."""
    selected = set(candidate_models)
    unknown = selected - {"gpt-5.4-mini", "gpt-5.5"}
    if not selected or unknown:
        raise ValueError("Deployment verification needs valid candidate models")
    required_models = selected | {"gpt-5.4-mini", "gpt-5.4"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot read deployment verification {path}: {error}"
        ) from error
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Deployment verification must use schema version 1")
    source = data.get("source")
    if source not in {
        "Azure Resource Manager deployment listing",
        "Azure Responses API model attestation",
    }:
        raise ValueError("Deployment verification has an invalid source")
    try:
        verified_at = datetime.fromisoformat(str(data["verifiedAt"]))
    except (KeyError, ValueError) as error:
        raise ValueError("Deployment verification has an invalid verifiedAt") from error
    if verified_at.tzinfo is None:
        raise ValueError("Deployment verification timestamp must include a timezone")
    age = datetime.now(timezone.utc) - verified_at.astimezone(timezone.utc)
    if age < timedelta(minutes=-5) or age > timedelta(hours=1):
        raise ValueError("Deployment verification must be no more than one hour old")

    endpoint = os.environ.get("IRIS_QA_AZURE_ENDPOINT", "").rstrip("/")
    if data.get("endpoint") != endpoint:
        raise ValueError("Deployment verification endpoint differs from the paid run")
    hostname = urlparse(endpoint).hostname or ""
    if data.get("accountName") != hostname.removesuffix(".openai.azure.com"):
        raise ValueError("Deployment verification account differs from the endpoint")
    if source == "Azure Resource Manager deployment listing":
        resource_group = os.environ.get("IRIS_QA_AZURE_RESOURCE_GROUP", "").strip()
        if not resource_group or data.get("resourceGroup") != resource_group:
            raise ValueError(
                "Deployment verification resource group differs from the paid run"
            )
        subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
        if not subscription_id or data.get("subscriptionId") != subscription_id:
            raise ValueError(
                "Deployment verification subscription differs from the paid run"
            )
    deployments = data.get("deployments")
    if (
        not isinstance(deployments, dict)
        or not required_models.issubset(deployments)
        or not set(deployments).issubset(EXPECTED_DEPLOYMENTS)
    ):
        raise ValueError("Deployment verification has an incomplete model mapping")
    for model in required_models:
        environment_name = EXPECTED_DEPLOYMENTS[model]
        expected_name = os.environ.get(environment_name, "").strip()
        item = deployments.get(model)
        if (
            not expected_name
            or not isinstance(item, dict)
            or item.get("deployment") != expected_name
            or item.get("model") != model
            or not isinstance(item.get("version"), str)
            or not item["version"].strip()
        ):
            raise ValueError(f"Deployment verification mismatch for {model}")
        if source == "Azure Responses API model attestation" and (
            item.get("responseStatus") != "completed"
            or not isinstance(item.get("inputTokens"), int)
            or item["inputTokens"] <= 0
            or not isinstance(item.get("outputTokens"), int)
            or item["outputTokens"] <= 0
        ):
            raise ValueError(f"Incomplete Responses API attestation for {model}")
    return data
