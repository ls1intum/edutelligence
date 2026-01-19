import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


def init():
    tracing_enabled = os.environ.get("SENTRY_ENABLE_TRACING", "False").lower() in (
        "true",
        "1",
    )
    failed_status_codes = {403, *range(500, 599)}

    sentry_environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    sample_rate=0.1 if sentry_environment == "staging" else 1.0

    sentry_sdk.init(
        dsn="https://17806b3674c44a10ac10345ba7201cc6@sentry.aet.cit.tum.de/8",
        environment=sentry_environment,
        server_name=os.environ.get("SENTRY_SERVER_NAME", "localhost"),
        release=os.environ.get("SENTRY_RELEASE", None),
        attach_stacktrace=os.environ.get("SENTRY_ATTACH_STACKTRACE", "False").lower()
        in ("true", "1"),
        max_request_body_size="always",
        traces_sample_rate=sample_rate if tracing_enabled else 0.0,
        profiles_sample_rate=sample_rate if tracing_enabled else 0.0,
        send_default_pii=True,
        integrations=[
            StarletteIntegration(
                transaction_style="endpoint",
                failed_request_status_codes=failed_status_codes,
            ),
            FastApiIntegration(
                transaction_style="endpoint",
                failed_request_status_codes=failed_status_codes,
            ),
            OpenAIIntegration(
                include_prompts=True,
            ),
        ],
    )
