---
title: Configuration
---

# Configuration

Copy `.env.example` to `.env`. Check every production value. The compose
files contain safe local defaults. An empty secret or a default secret is not
safe for an instance that is open to the internet.

| Variable | Purpose |
| --- | --- |
| `LOGOS_DOMAIN` | Hostname for UI and API routing |
| `ACME_EMAIL` | Email address for Let's Encrypt certificates |
| `LOGOS_CORS_ALLOWED_ORIGINS` | Exact browser origins that the API allows |
| `KEYCLOAK_ISSUER_URI` | OIDC issuer that validates user tokens |
| `KEYCLOAK_CLIENT_ID` | Public OIDC client of the UI |
| `LOGOS_INTERNAL_SECRET` | Shared secret between the Spring API and the orchestrator |
| `PROMETHEUS_API_KEY` | Credential that the metrics endpoint requires |
| `HF_TOKEN` | Optional token for gated Hugging Face models |

For CORS, use exact origins with the scheme and the port. Do not use `*` with
browser requests that send credentials. Do not put `.env` in source control.

## Provider endpoints

Logos sends a provider's credentials only over HTTPS. Plain HTTP is allowed
only on loopback (`localhost`, `127.0.0.1`, `::1`). If a provider has an API
key and its endpoint is plain HTTP on another host, Logos refuses the request
and logs `Refusing to send the credentials of provider … over an insecure
transport`.

To use an upstream on another host, put it behind HTTPS (for example behind
Traefik with a certificate). An upstream that needs no credentials is not
affected: when the provider has no API key, Logos forwards over plain HTTP.
Worker nodes (`logosnode` providers) connect over their own websocket and are
not affected either.
