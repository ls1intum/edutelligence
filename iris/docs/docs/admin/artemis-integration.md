---
title: Artemis Integration
---

# Artemis Integration

Iris is designed to work as the AI backend for [Artemis](https://github.com/ls1intum/Artemis). This page explains how to connect the two systems.

## How It Works

Artemis communicates with Iris over HTTP. When a student interacts with an AI feature (e.g., the Iris chat tutor), Artemis sends a request to the Iris REST API. Iris processes the request through the appropriate pipeline, calls the configured LLM, and sends results back to Artemis via a webhook callback.

Authentication between Artemis and Iris uses a **shared secret token**. Both sides must be configured with the same value.

## Configuring Artemis

In Artemis's `application-artemis.yml` (or the equivalent Spring profile), add the following:

```yaml
iris:
  enabled: true
  url: http://iris-host:8000
  secret-token: your-shared-secret-token
```

| Key                 | Description                                                               |
| ------------------- | ------------------------------------------------------------------------- |
| `iris.enabled`      | Set to `true` to activate Iris features in the Artemis UI                 |
| `iris.url`          | Full URL where Iris is reachable from the Artemis server (including port) |
| `iris.secret-token` | Shared secret used to authenticate requests between Artemis and Iris      |

:::warning
The `iris.url` must be reachable from the Artemis server process, not from the user's browser. If both services run in Docker on the same host, use the Docker network hostname (e.g., `http://pyris-app:8000`).
:::

## Configuring Iris

In Iris's `application.yml`, configure the API key that matches the Artemis secret token:

```yaml
api_keys:
  - token: "your-shared-secret-token"
```

The token value here **must exactly match** the `iris.secret-token` value in Artemis's configuration. Iris validates incoming requests by checking the `Authorization` header against this list of tokens.

:::danger
Use a strong, randomly generated token (at least 32 characters). Never reuse tokens across environments (dev, staging, production).
:::

You can configure multiple API keys if multiple Artemis instances connect to the same Iris deployment:

```yaml
api_keys:
  - token: "token-for-artemis-production"
  - token: "token-for-artemis-staging"
```

## Network Architecture

A typical production setup looks like this:

```
[Student Browser] --> [Artemis] --HTTP--> [Iris :8000] --HTTPS--> [LLM Provider]
                                              |
                                              +--> [Weaviate :8001]
```

Key network requirements:

- **Artemis to Iris**: Artemis must be able to reach Iris on the configured `iris.url`. Default port is `8000`.
- **Iris to Artemis**: Iris sends webhook callbacks to the `artemis_base_url` provided in each pipeline request. Ensure Iris can reach Artemis's API.
- **Iris to LLM providers**: Iris must have outbound HTTPS access to your configured LLM endpoints (e.g., `api.openai.com`, Azure endpoints, or local Ollama).
- **Iris to Weaviate**: Internal connection, typically on the same Docker network.

## Health Checks

Artemis checks Iris's availability using the health endpoint:

```
GET http://iris-host:8000/api/v1/health/
Authorization: <shared-secret-token>
```

If the health check fails, Artemis will show Iris features as unavailable in the UI.

You can manually verify connectivity from the Artemis server:

```bash
curl -H "Authorization: your-shared-secret-token" http://iris-host:8000/api/v1/health/
```

A healthy response looks like:

```json
{
  "isHealthy": true,
  "modules": {
    "Weaviate": { "status": "UP" },
    "Pipelines": { "status": "UP" }
  }
}
```

## Troubleshooting Connectivity

### Artemis cannot reach Iris

1. **Check network reachability**: From the Artemis host, verify you can reach Iris:

   ```bash
   curl -v http://iris-host:8000/docs
   ```

2. **Check Docker networking**: If both run in Docker, ensure they share a network or that ports are correctly published.

3. **Check firewall rules**: Port `8000` (or your configured `PYRIS_PORT`) must be open between the hosts.

4. **Verify the URL in Artemis config**: The `iris.url` value must not have a trailing slash and must include the port.

### Authentication failures (401/403)

1. **Token mismatch**: The most common issue. Verify the token in `application.yml` (`api_keys[].token`) matches `iris.secret-token` in Artemis exactly. Watch for trailing whitespace or newlines.

2. **Missing Authorization header**: Ensure Artemis is sending the token in the `Authorization` header.

### Iris cannot call back to Artemis

Iris sends results back via webhook URLs derived from `artemis_base_url` in the pipeline request. If callbacks fail:

1. Verify Iris can reach the Artemis server URL.
2. Check Iris logs for HTTP errors on callback attempts.
3. Ensure Artemis's API endpoints are not blocked by a reverse proxy or firewall.

For more issues, see the [Troubleshooting](./troubleshooting.md) page.
