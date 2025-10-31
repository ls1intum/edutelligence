import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


def init():
    sentry_sdk.init(
        dsn="https://17806b3674c44a10ac10345ba7201cc6@sentry.aet.cit.tum.de/8",
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        server_name=os.environ.get("SENTRY_SERVER_NAME", "localhost"),
        release=os.environ.get("SENTRY_RELEASE", None),
        attach_stacktrace=os.environ.get("SENTRY_ATTACH_STACKTRACE", "False").lower()
        in ("true", "1"),
        max_request_body_size="always",
        enable_tracing=os.environ.get("SENTRY_ENABLE_TRACING", "False").lower()
        in ("true", "1"),
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        send_default_pii=True,
        integrations=[
            StarletteIntegration(
                transaction_style="endpoint",
                failed_request_status_codes=[403, range(500, 599)],
            ),
            FastApiIntegration(
                transaction_style="endpoint",
                failed_request_status_codes=[403, range(500, 599)],
            ),
            OpenAIIntegration(
                include_prompts=True,
            ),
        ],
    )
