---
title: Troubleshooting
---

# Troubleshooting

This page covers common issues encountered when deploying and operating Iris.

## Startup Failures

### `APPLICATION_YML_PATH environment variable is not set`

Iris requires the `APPLICATION_YML_PATH` environment variable to locate its configuration file. In Docker deployments, this is set automatically by the compose files. If running manually:

```bash
export APPLICATION_YML_PATH=/path/to/application.yml
export LLM_CONFIG_PATH=/path/to/llm_config.yml
poetry run uvicorn iris.main:app --host 0.0.0.0 --port 8000
```

### `Configuration file not found`

The path specified in `APPLICATION_YML_PATH` does not exist or is not readable. Verify:

```bash
ls -la $APPLICATION_YML_PATH
```

In Docker, check that the volume mount is correct in your compose file:

```yaml
volumes:
  - /host/path/to/application.yml:/config/application.yml:ro
```

### `Error parsing YAML file`

The `application.yml` or `llm_config.yml` contains invalid YAML syntax. Common causes:

- Incorrect indentation (YAML is whitespace-sensitive)
- Missing quotes around strings containing special characters
- Tabs instead of spaces

Validate your file:

```bash
python -c "import yaml; yaml.safe_load(open('application.yml'))"
```

### `LangFuse public_key and secret_key are required when enabled=True`

You set `langfuse.enabled: true` in `application.yml` but did not provide both `public_key` and `secret_key`. Either provide the keys or set `enabled: false`:

```yaml
langfuse:
  enabled: false
```

## Connectivity Issues

### Artemis Cannot Reach Iris

**Symptoms**: Iris features are greyed out or unavailable in the Artemis UI.

1. **Verify Iris is running**:

   ```bash
   curl http://iris-host:8000/docs
   ```

2. **Check the health endpoint** (requires authentication):

   ```bash
   curl -H "Authorization: your-token" http://iris-host:8000/api/v1/health/
   ```

3. **Verify Artemis configuration** in `application-artemis.yml`:

   ```yaml
   iris:
     enabled: true
     url: http://iris-host:8000 # No trailing slash
     secret-token: your-token
   ```

4. **Docker networking**: If both services run in Docker on the same host, use the container name or Docker network DNS instead of `localhost`:
   ```yaml
   iris:
     url: http://pyris-app:8000
   ```

See also: [Artemis Integration](./artemis-integration.md)

### Iris Cannot Reach Weaviate

**Symptoms**: Health endpoint shows Weaviate as `DOWN`. Ingestion and RAG-based features fail.

1. **Check Weaviate is running**:

   ```bash
   docker compose -f <compose-file> ps weaviate
   ```

2. **Check Weaviate logs**:

   ```bash
   docker compose -f <compose-file> logs weaviate
   ```

3. **Verify `application.yml` settings**: When running in Docker Compose, `host` should be `weaviate` (the service name), not `localhost`:

   ```yaml
   weaviate:
     host: "weaviate"
     port: "8001"
     grpc_port: "50051"
   ```

4. **Test Weaviate directly**:
   ```bash
   curl http://localhost:8001/v1/.well-known/ready
   ```

See also: [Weaviate Setup](./weaviate-setup.md)

### Iris Cannot Reach LLM Provider

**Symptoms**: Pipeline executions fail with connection errors. Logs show timeout or DNS resolution failures.

1. **Verify outbound connectivity** from the Iris container:

   ```bash
   docker exec pyris-app python -c "import urllib.request; urllib.request.urlopen('https://api.openai.com')"
   ```

2. **Check API keys** in `llm_config.yml`: Ensure the `api_key` values are valid and have not expired.

3. **For Azure endpoints**: Verify the `endpoint` URL is correct and the `azure_deployment` name matches your Azure deployment.

4. **For Ollama**: Ensure the Ollama server is running and accessible from the Iris container. If Ollama runs on the Docker host, use `host.docker.internal` as the endpoint hostname.

See also: [LLM Configuration](./llm-configuration.md)

## Authentication Errors

### `401 Unauthorized` on API Requests

The `Authorization` header value does not match any token in `application.yml`:

```yaml
api_keys:
  - token: "your-secret-token"
```

Common causes:

- Token mismatch between Artemis's `iris.secret-token` and Iris's `api_keys[].token`
- Trailing whitespace or newline characters in the token
- Copying the token with surrounding quotes (the YAML value should not include literal quote characters)

### `403 Forbidden`

Iris returns 403 when authentication succeeds but the request is invalid. Check Iris logs for details:

```bash
docker compose -f <compose-file> logs pyris-app | grep "403\|forbidden\|Forbidden"
```

## LLM Configuration Errors

### Missing Models at Startup

Iris logs warnings when pipelines cannot find required models. Example:

```
WARNING: Pipeline 'exercise_chat' could not resolve model for role 'primary'
```

**Fix**: Ensure `llm_config.yml` contains models matching what the pipelines expect. At minimum, configure:

- A chat model (e.g., `openai_chat` type)
- An embedding model (e.g., `openai_embedding` or `azure_embedding` type)

### Model API Errors During Pipeline Execution

If a model is configured but API calls fail:

- **Rate limiting**: You may be hitting the provider's rate limits. Check the LLM provider dashboard.
- **Quota exceeded**: Your API key may have exhausted its budget.
- **Model deprecation**: The `model` name may no longer be valid. Check the provider's documentation for current model names.

## Port Conflicts

If services fail to start due to port conflicts:

```bash
# Change the Iris port
export PYRIS_PORT=8080

# Change the Weaviate ports
export WEAVIATE_PORT=9001
export WEAVIATE_GRPC_PORT=50052
```

Remember to update `application.yml` with the new Weaviate ports if you change them.

## Memory and Resource Issues

### Iris Container Running Out of Memory

Iris itself is lightweight, but LLM responses with very long contexts can spike memory usage. If the container is OOM-killed:

- Increase the Docker memory limit for the `pyris-app` service
- Monitor memory usage: `docker stats pyris-app`

### Weaviate Disk Usage

Weaviate warns at 80% disk usage and may refuse writes when full.

```bash
# Check disk usage of the Weaviate data volume
du -sh /path/to/weaviate-data
```

Solutions:

- Increase disk space
- Delete unused collections through the Iris API
- Re-index only the courses that are currently active

### Docker Resource Allocation

If services fail to start or crash immediately:

- On Docker Desktop: Increase memory allocation in Docker Desktop settings (recommend at least 4 GB for the full stack)
- On Linux: Ensure sufficient system resources and check `dmesg` for OOM killer activity

## Log Locations

| Source                | How to Access                                                   |
| --------------------- | --------------------------------------------------------------- |
| Iris application logs | `docker compose -f <compose-file> logs -f pyris-app`            |
| Weaviate logs         | `docker compose -f <compose-file> logs -f weaviate`             |
| Nginx logs (if used)  | `docker compose -f <compose-file> logs -f nginx`                |
| Sentry dashboard      | Check your Sentry project (see [Monitoring](./monitoring.md))   |
| LangFuse dashboard    | Check your LangFuse project (see [Monitoring](./monitoring.md)) |

## Debugging Tips

1. **Enable verbose logging**: Set `SENTRY_ATTACH_STACKTRACE=true` to get full stack traces in Sentry.

2. **Check the Swagger UI**: Navigate to `http://iris-host:8000/docs` to interactively test API endpoints.

3. **Validate configuration files** before deploying:

   ```bash
   python -c "
   import yaml
   with open('application.yml') as f:
       print('application.yml:', 'OK' if yaml.safe_load(f) else 'EMPTY')
   with open('llm_config.yml') as f:
       print('llm_config.yml:', 'OK' if yaml.safe_load(f) else 'EMPTY')
   "
   ```

4. **Test connectivity step by step**: Verify each connection independently (Iris to Weaviate, Iris to LLM, Artemis to Iris) before debugging pipeline failures.

5. **Use LangFuse** for pipeline debugging: Enable LangFuse tracing to see exactly which LLM calls are made, what prompts are sent, and where failures occur. See [Monitoring](./monitoring.md) for setup.
