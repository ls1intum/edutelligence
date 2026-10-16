import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.openai import OpenAIIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

# Keys whose values are callback credentials. Request bodies from Artemis carry the token in
# settings.authenticationToken, and claimed ingestion jobs are dicts with the same key.
_CREDENTIAL_KEYS = [
    "authenticationToken",
    "authentication_token",
    "auth_token",
    "_auth_token",
]


def credential_safety_options() -> dict:
    """The client options that keep callback credentials out of Sentry events."""
    return {
        # send_default_pii as in init, so only the credential keys are added to what was scrubbed before.
        "event_scrubber": EventScrubber(
            denylist=DEFAULT_DENYLIST + _CREDENTIAL_KEYS,
            recursive=True,
            send_default_pii=True,
        ),
        # Without local variables: once a callback token is put into a request header, it sits as
        # plain bytes in locals of the HTTP client, where no key-based scrubbing can find it.
        "include_local_variables": False,
    }


def init():
    tracing_enabled = os.environ.get("SENTRY_ENABLE_TRACING", "False").lower() in (
        "true",
        "1",
    )
    failed_status_codes = {403, *range(500, 599)}

    sentry_environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    sample_rate = 0.01 if sentry_environment == "staging" else 1.0

    sentry_sdk.init(
        dsn="https://17806b3674c44a10ac10345ba7201cc6@sentry.aet.cit.tum.de/8",
        environment=sentry_environment,
        server_name=os.environ.get("SENTRY_SERVER_NAME", "localhost"),
        release=os.environ.get("SENTRY_RELEASE", None),
        attach_stacktrace=os.environ.get("SENTRY_ATTACH_STACKTRACE", "False").lower()
        in ("true", "1"),
        max_request_body_size="always",
        **credential_safety_options(),
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
