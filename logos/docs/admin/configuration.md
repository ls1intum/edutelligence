---
title: Configuration
---

# Configuration

Copy `.env.example` to `.env` and review every production value. The compose
files provide safe local defaults, but an empty or default secret is not
suitable for an internet-facing instance.

| Variable | Purpose |
| --- | --- |
| `LOGOS_DOMAIN` | Hostname used for UI and API routing |
| `ACME_EMAIL` | Email used for Let's Encrypt certificates |
| `LOGOS_CORS_ALLOWED_ORIGINS` | Exact browser origins allowed by the API |
| `KEYCLOAK_ISSUER_URI` | OIDC issuer used to validate user tokens |
| `KEYCLOAK_CLIENT_ID` | Public OIDC client used by the UI |
| `LOGOS_INTERNAL_SECRET` | Shared secret between the Spring API and orchestrator |
| `PROMETHEUS_API_KEY` | Credential required by the metrics endpoint |
| `HF_TOKEN` | Optional token for gated Hugging Face models |

Use exact origins including scheme and port for CORS; do not use `*` with
credentialed browser requests. Keep `.env` out of source control.
