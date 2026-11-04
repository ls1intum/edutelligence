---
title: Monitoring
---

# Monitoring

Iris integrates with **Sentry** for error tracking and **LangFuse** for LLM observability.

## Sentry

[Sentry](https://sentry.io/) captures errors, exceptions, and performance data from the Iris application.

### How It Works

Sentry is initialized at application startup in `iris/src/iris/sentry.py`. It includes integrations for:

- **FastAPI / Starlette**: Captures unhandled exceptions in API endpoints. HTTP status codes 403 and 500-599 are reported as errors.
- **OpenAI SDK**: Captures LLM call details including prompts (useful for debugging pipeline issues).

### Configuration

Sentry is configured entirely through environment variables. Sentry is off unless `SENTRY_DSN` is set; without it, Iris sends no events and the other `SENTRY_*` variables have no effect on Sentry. `SENTRY_ENVIRONMENT` is still used as the LangFuse environment tag.

| Variable                   | Default       | Description                                                    |
| -------------------------- | ------------- | -------------------------------------------------------------- |
| `SENTRY_DSN`               | _unset_       | Sentry project DSN. Leave unset to turn Sentry off             |
| `SENTRY_ENVIRONMENT`       | `development` | Environment tag (e.g., `production`, `staging`, `development`) |
| `SENTRY_ENABLE_TRACING`    | `False`       | Enable performance tracing (traces and profiles)               |
| `SENTRY_SERVER_NAME`       | `localhost`   | Server name identifier                                         |
| `SENTRY_RELEASE`           | `None`        | Release/version tag for tracking deployments                   |
| `SENTRY_ATTACH_STACKTRACE` | `False`       | Attach stack traces to all events (not just exceptions)        |

### Sampling Rates

- **Staging** (`SENTRY_ENVIRONMENT=staging`): 1% sample rate for traces and profiles to reduce volume.
- **All other environments**: 100% sample rate (every trace is captured).

:::tip
Set `SENTRY_ENABLE_TRACING=true` in production to get performance insights. The sampling rate automatically adjusts based on the environment.
:::

### Example Configuration

Set these in the `env_vars` section of `application.yml`. Iris sets them as environment variables at startup, before Sentry starts. The Docker Compose files do not pass variables from `docker.env` into the `pyris-app` container, so do not put them there.

```yaml
env_vars:
  SENTRY_DSN: "https://<key>@<sentry-host>/<project-id>"
  SENTRY_ENVIRONMENT: "production"
  SENTRY_ENABLE_TRACING: "true"
  SENTRY_SERVER_NAME: "iris-prod-01"
  SENTRY_RELEASE: "v2.1.0"
```

## LangFuse

[LangFuse](https://langfuse.com/) provides detailed observability for LLM interactions -- tracking prompts, completions, latency, token usage, and costs across all pipeline executions.

### How It Works

LangFuse tracing is deeply integrated into Iris's pipeline system:

- The `@observe` decorator traces any function, with support for span types like `generation`, `agent`, `tool`, and `retriever`.
- `TracingContext` propagates rich metadata (user ID, course, exercise, lecture, variant) through the pipeline, linking every LLM call to its educational context.
- Every chat model call is a generation with the model name and token counts: OpenAI and Azure OpenAI through the instrumented `langfuse.openai` client, Ollama through `record_generation`.
- `TracedThreadPoolExecutor` ensures that threaded operations produce properly nested traces instead of orphaned top-level entries.

### Configuration

LangFuse is configured in `application.yml`:

```yaml
langfuse:
  enabled: true
  public_key: "pk-lf-..."
  secret_key: "sk-lf-..." # pragma: allowlist secret
  host: "https://cloud.langfuse.com"
```

| Field        | Required     | Default                      | Description                                  |
| ------------ | ------------ | ---------------------------- | -------------------------------------------- |
| `enabled`    | No           | `false`                      | Enable or disable LangFuse tracing           |
| `public_key` | When enabled | --                           | Your LangFuse public key                     |
| `secret_key` | When enabled | --                           | Your LangFuse secret key                     |
| `host`       | No           | `https://cloud.langfuse.com` | LangFuse server URL (change for self-hosted) |

:::danger
When `enabled` is `true`, both `public_key` and `secret_key` are required. Iris will fail to start if they are missing.
:::

### Self-Hosted LangFuse

If you run a self-hosted LangFuse instance, set the `host` field to your instance URL:

```yaml
langfuse:
  enabled: true
  public_key: "pk-lf-..."
  secret_key: "sk-lf-..." # pragma: allowlist secret
  host: "https://langfuse.your-domain.com"
```

### What Gets Traced

When enabled, LangFuse captures:

- **Pipeline executions**: Each pipeline run creates a top-level trace with metadata (pipeline name, variant, user, course, exercise).
- **LLM generations**: Every LLM call is recorded with prompt, completion, token counts, and model information.
- **Tool calls**: Agent tool invocations are tracked as child spans.
- **Retrieval operations**: RAG retrieval steps are logged.
- **Artemis deep links**: Traces include links back to the course, exercise, and lecture in Artemis for easy navigation.

### Graceful Degradation

LangFuse tracing is designed to be non-intrusive:

- If the `langfuse` package is not installed, tracing is silently disabled.
- If the LangFuse server is unreachable, pipeline execution continues normally.
- The `@observe` decorator becomes a no-op pass-through when tracing is disabled, adding zero overhead.

## Logging

Iris uses Python's standard `logging` module with structured log formatting. Logs include:

- **Request correlation IDs**: Every HTTP request gets a unique ID for tracing through log entries.
- **Request duration**: Each completed request logs its processing time in milliseconds.
- **Health check suppression**: Health check endpoint logs are suppressed to reduce noise.

View application logs via Docker:

```bash
docker compose -f <compose-file> logs -f pyris-app
```

The log verbosity for third-party libraries is configured in `iris/src/iris/common/logging_config.py`.

## Watchdog

A watchdog thread (`iris/src/iris/watchdog.py`) restarts Iris when a model client's connection pool deadlocks: every request on that model would otherwise hang without any error. It checks the pool locks every 5 seconds. When a lock stays held on two checks in a row, it logs a thread dump, fails the open runs ("Iris had to restart"), sends an alert and exits; Docker (`restart: unless-stopped`) starts Iris again. At most one restart per 30 minutes; after that, Iris stays up and sends an urgent alert so someone restarts it by hand. Set `watchdog_enabled: false` in `application.yml` to turn it off.

Alerts go to [Pushover](https://pushover.net/) when `PYRIS_PUSHOVER_APP_TOKEN` and `PYRIS_PUSHOVER_USER_KEY` are set (for example in the compose env file); `PYRIS_ALERT_NAME` names the instance. Without them, alerts are only logged.

To see all thread stacks of a running Iris, for example when answers hang: `docker kill -s USR1 pyris-app`, then read the container log.

The container has a memory limit (`PYRIS_MEMORY_LIMIT`, default `6g`), so running out of memory restarts Iris instead of making the host kill other services.
