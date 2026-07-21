from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from iris.qa.cost import BudgetExceeded, BudgetGuard, SpendLedger

PROBE_INPUT_CEILING = 256
PROBE_OUTPUT_CEILING = 128


def run_responses_attestation(
    *,
    rate_card,
    ledger_path: Path,
    hard_limit: Decimal,
    max_cost: Decimal,
    output: Path,
) -> dict:
    """Attest local Azure deployment names through tiny Responses API calls."""
    if os.environ.get("IRIS_QA_AZURE_AUTH_MODE") != "api_key":
        raise ValueError("Responses attestation currently requires local API-key auth")
    endpoint = os.environ.get("IRIS_QA_AZURE_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("IRIS_QA_AZURE_API_KEY", "")
    if not endpoint or not api_key:
        raise ValueError("Azure endpoint and API key must be configured")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".openai.azure.com")
    ):
        raise ValueError("Azure endpoint is invalid")

    deployments = {
        "gpt-5.4-mini": os.environ.get("IRIS_QA_GPT_54_MINI_DEPLOYMENT", ""),
        "gpt-5.5": os.environ.get("IRIS_QA_GPT_55_DEPLOYMENT", ""),
        "gpt-5.4": os.environ.get("IRIS_QA_JUDGE_DEPLOYMENT", ""),
    }
    if any(not deployment for deployment in deployments.values()):
        raise ValueError("All three Azure deployment names must be configured")
    if len(set(deployments.values())) != 3:
        raise ValueError("Candidate and judge deployments must be distinct")

    rates = {rate.model: rate for rate in (*rate_card.candidates, rate_card.judge)}
    estimate = sum(
        (
            rates[model].cost(PROBE_INPUT_CEILING, PROBE_OUTPUT_CEILING)
            for model in deployments
        ),
        Decimal(0),
    )
    if estimate > max_cost:
        raise ValueError(
            f"Attestation refused: pessimistic ${estimate:.4f} exceeds "
            f"--max-cost-usd ${max_cost:.4f}"
        )
    ledger = SpendLedger(ledger_path)
    starting_spend = ledger.total()
    invocation_limit = min(hard_limit, starting_spend + max_cost)
    guard = BudgetGuard(ledger, invocation_limit)
    guard.require_capacity(estimate)
    client = OpenAI(
        base_url=endpoint + "/openai/v1/",
        api_key=api_key,
        default_headers={"api-key": api_key},
        timeout=60,
        max_retries=0,
    )
    verified = {}
    for model, deployment in deployments.items():
        probe_reserve = rates[model].cost(PROBE_INPUT_CEILING, PROBE_OUTPUT_CEILING)
        guard.require_capacity(probe_reserve)
        try:
            response = client.responses.create(
                model=deployment,
                input="Reply with exactly OK.",
                max_output_tokens=PROBE_OUTPUT_CEILING,
                reasoning={"effort": "low"},
                store=False,
            )
        except (
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
            InternalServerError,
            RateLimitError,
        ):
            guard.record_reservation(
                run_id="deployment-attestation",
                scenario_id=model,
                pipeline="ambiguous-provider-call-reserve",
                model=model,
                cost_usd=probe_reserve,
            )
            raise
        usage = getattr(response, "usage", None)
        try:
            record = guard.record_usage(
                run_id="deployment-attestation",
                scenario_id=model,
                pipeline="responses-api-attestation",
                rate=rates[model],
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            )
        except BudgetExceeded as error:
            if "omitted paid token usage" in str(error):
                guard.record_reservation(
                    run_id="deployment-attestation",
                    scenario_id=model,
                    pipeline="ambiguous-provider-call-reserve",
                    model=model,
                    cost_usd=probe_reserve,
                )
            raise
        response_model = getattr(response, "model", None)
        response_status = getattr(response, "status", None)
        if response_model != model or response_status != "completed":
            raise RuntimeError(
                f"Deployment {deployment!r} reported model/status "
                f"{response_model!r}/{response_status!r}; expected "
                f"{model!r}/'completed'"
            )
        verified[model] = {
            "deployment": deployment,
            "model": response_model,
            "version": "provider-reported",
            "responseStatus": response_status,
            "inputTokens": record.input_tokens,
            "outputTokens": record.output_tokens,
        }

    result = {
        "version": 1,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Azure Responses API model attestation",
        "accountName": parsed.hostname.removesuffix(".openai.azure.com"),
        "endpoint": endpoint,
        "deployments": verified,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    output.chmod(0o600)
    return result
