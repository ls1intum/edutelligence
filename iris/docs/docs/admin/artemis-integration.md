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

You can configure multiple API keys if multiple Artemis instances connect to the same Iris deployment. Give every Artemis installation its own key and name the installation in `allowed_base_urls`:

```yaml
api_keys:
  - token: "token-for-artemis-staging"
    allowed_base_urls:
      - "https://artemis-staging.example.org"
  - token: "token-for-artemis-test"
    allowed_base_urls:
      - "https://artemis-test.example.org"
```

`allowed_base_urls` lists the base URLs of the Artemis installations that may use the key. Every request names the installation it comes from, as `artemisBaseUrl` in the request body, as the `base_url` query parameter, or in the `X-Artemis-Base-Url` header of the health check. This is the `server.url` of the Artemis installation. Iris keeps the data of the installations apart by this URL, and with `allowed_base_urls` it answers a request for another installation with `403`.

- Spellings that differ only in the case of the scheme and host, in a default port (`:443` for https, `:80` for http), or in trailing slashes are the same URL. A different host, port, scheme or path is a different URL.
- A key without `allowed_base_urls` is accepted for every installation. This keeps existing configurations working; set the list wherever more than one Artemis installation, or any other party, can reach Iris.
- An entry that is not an http(s) base URL stops Iris at start-up, so that a typo does not leave a key that nobody can use.

## Network Architecture

Place Iris and Weaviate in a private network that only the Artemis servers can reach, and run one Iris per environment that holds real course data. See [Network Layout](./network-layout.md) for the recommended layout.

A typical production setup looks like this:

```
[Student Browser] --> [Artemis] --HTTP--> [Iris :8000] --HTTPS--> [LLM Provider]
                                              |
                                              +--> [Weaviate :8001]
```

Key network requirements:

- **Artemis to Iris**: Artemis must be able to reach Iris on the configured `iris.url`. Default port is `8000`.
- **Iris to Artemis**: Iris sends webhook callbacks to the `artemis_base_url` provided in each pipeline request. Ensure Iris can reach Artemis's API.
- **Lecture ingestion**: Iris claims lecture ingestion jobs from every Artemis that health-checks it; Artemis does not send them. Iris learns the Artemis URL from the `X-Artemis-Base-Url` header of the health check, so it must be able to reach that URL. Settings: `ingestion_worker` in the Iris configuration.
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
   curl -v -H "Authorization: your-shared-secret-token" http://iris-host:8000/api/v1/health/
   ```

2. **Check Docker networking**: If both run in Docker, ensure they share a network or that ports are correctly published.

3. **Check firewall rules**: Port `8000` (or your configured `PYRIS_PORT`) must be open between the hosts.

4. **Verify the URL in Artemis config**: The `iris.url` value must not have a trailing slash and must include the port.

### Authentication failures (401/403)

`401` means the `Authorization` header is missing. `403` means the value is not one of the configured tokens, or the key is not allowed for the base URL that the request names.

1. **Token mismatch**: The most common issue. Verify the token in `application.yml` (`api_keys[].token`) matches `iris.secret-token` in Artemis exactly. Watch for trailing whitespace or newlines.

2. **Missing Authorization header**: Ensure Artemis is sending the token in the `Authorization` header.

3. **Base URL not allowed**: If the key has `allowed_base_urls`, the Iris log names the rejected base URL. It has to match the `server.url` of the Artemis installation (see above for what counts as the same URL).

### Iris cannot call back to Artemis

Iris sends results back via webhook URLs derived from `artemis_base_url` in the pipeline request. If callbacks fail:

1. Verify Iris can reach the Artemis server URL.
2. Check Iris logs for HTTP errors on callback attempts.
3. Ensure Artemis's API endpoints are not blocked by a reverse proxy or firewall.

For more issues, see the [Troubleshooting](./troubleshooting.md) page.
