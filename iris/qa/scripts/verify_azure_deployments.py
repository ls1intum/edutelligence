"""Verify Azure deployment-to-model bindings from an ARM deployment listing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_ENV = {
    "gpt-5.4-mini": "IRIS_QA_GPT_54_MINI_DEPLOYMENT",
    "gpt-5.5": "IRIS_QA_GPT_55_DEPLOYMENT",
    "gpt-5.4": "IRIS_QA_JUDGE_DEPLOYMENT",
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set")
    return value


def verify_deployments(
    payload: object, expected: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Return verified deployment metadata or reject any ambiguous binding."""
    if not isinstance(payload, list):
        raise ValueError("Azure deployment listing must be a JSON list")
    entries: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("Azure deployment listing contains an invalid entry")
        if item["name"] in entries:
            duplicate_name = item["name"]
            raise ValueError(f"Duplicate Azure deployment {duplicate_name!r}")
        entries[item["name"]] = item

    if len(set(expected.values())) != len(expected):
        raise ValueError("Candidate and judge deployment names must be distinct")
    verified = {}
    for expected_model, deployment_name in expected.items():
        entry = entries.get(deployment_name)
        if entry is None:
            raise ValueError(f"Azure deployment {deployment_name!r} was not found")
        properties = entry.get("properties")
        model = properties.get("model") if isinstance(properties, dict) else None
        actual_model = model.get("name") if isinstance(model, dict) else None
        model_format = model.get("format") if isinstance(model, dict) else None
        version = model.get("version") if isinstance(model, dict) else None
        state = (
            properties.get("provisioningState")
            if isinstance(properties, dict)
            else None
        )
        if model_format != "OpenAI" or actual_model != expected_model:
            raise ValueError(
                f"Azure deployment {deployment_name!r} serves "
                f"{model_format!r}/{actual_model!r}; expected "
                f"'OpenAI'/{expected_model!r}"
            )
        if not isinstance(version, str) or not version.strip():
            raise ValueError(
                f"Azure deployment {deployment_name!r} has no model version"
            )
        if state != "Succeeded":
            raise ValueError(
                f"Azure deployment {deployment_name!r} is not ready: {state!r}"
            )
        verified[expected_model] = {
            "deployment": deployment_name,
            "model": actual_model,
            "version": version,
        }
    return verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    endpoint = _required("IRIS_QA_AZURE_ENDPOINT").rstrip("/")
    hostname = urlparse(endpoint).hostname or ""
    account_name = hostname.removesuffix(".openai.azure.com")
    if not account_name or account_name == hostname:
        raise ValueError("IRIS_QA_AZURE_ENDPOINT is not an Azure OpenAI endpoint")
    expected = {model: _required(name) for model, name in EXPECTED_ENV.items()}
    verified = verify_deployments(json.load(sys.stdin), expected)
    result = {
        "version": 1,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Azure Resource Manager deployment listing",
        "subscriptionId": _required("AZURE_SUBSCRIPTION_ID"),
        "resourceGroup": _required("IRIS_QA_AZURE_RESOURCE_GROUP"),
        "accountName": account_name,
        "endpoint": endpoint,
        "deployments": verified,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    output.chmod(0o600)
    for model, metadata in verified.items():
        deployment = metadata["deployment"]
        version = metadata["version"]
        print(f"VERIFIED {model} -> {deployment} ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
