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
- LangChain operations are traced via a `CallbackHandler` that filters out internal noise (e.g., `RunnableLambda`, `RunnablePassthrough`).
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

## Watchdog and Alerts

A watchdog thread inside Iris (`iris/src/iris/reliability/`) protects chat runs and the process.

### Chat Answer Deadlines

A chat run that has not sent its answer in time is failed towards Artemis, so the student sees an error instead of an endless wait.

| Path                    | Deadline | Setting                                      |
| ----------------------- | -------- | -------------------------------------------- |
| Cloud, default variant  | 120 s    | `reliability.chat_deadline_seconds`          |
| Cloud, advanced variant | 270 s    | `reliability.chat_advanced_deadline_seconds` |
| Local models            | 360 s    | `reliability.chat_local_deadline_seconds`    |

The deadline runs from the start of the run until the answer is sent. After that, the run has `reliability.post_answer_grace_seconds` (120 s) for its title, suggestions and compaction; then the watchdog closes it as finished. Artemis drops a chat job 300 s after its last status, so the watchdog re-sends `RUNNING` for a chat run that was quiet for 60 s.

### Self-Restart

The watchdog restarts the process only on direct signs that it is broken, never because a model is slow:

- the connection pool lock of a model client stays held for two checks in a row,
- garbage collection stopped while objects pile up,
- the event loop did not run for 30 s.

The last two checks start 5 minutes after startup. When one of them fires, Iris writes a thread dump, fails its open runs (chat, tutor suggestions, struggle interventions), sends an alert and exits; Docker (`restart: unless-stopped`) starts it again. The local `pyris-dev.yml` uses `restart: "no"`, so there the container stays stopped. At most one self-restart per 30 minutes and two per 6 hours are allowed. Above that, or if the restart history cannot be read, Iris stays up, reports itself unhealthy and sends an urgent alert. It then fails only the runs on the stuck model (or all runs if garbage collection or the event loop stopped); runs on other models can still finish. Set `reliability.self_restart: false` to never restart, or `reliability.enabled: false` to turn the watchdog off.

`GET /api/v1/health/liveness` returns 200 while the process works and 503 after the watchdog found it broken. The Docker health check uses it. It needs no token and returns no data.

### Diagnostics

The watchdog keeps thread dumps, the restart history and an exit marker in `reliability.diagnostics_dir` (default `/data/diagnostics`). The production compose files mount it from `PYRIS_DIAGNOSTICS_DIR`. Set that to an absolute host path outside the repository clone, so a redeploy does not delete it.

To take a thread dump of a running Iris, for example when chat answers hang:

```bash
docker exec pyris-app touch /data/diagnostics/dump-now
```

The dump lists the oldest run first, folds identical stacks and shows the state of garbage collection and of every model's connection pool. `docker kill -s USR2 pyris-app` does the same while the main thread still runs Python code, so the file is the reliable way; `docker kill -s USR1 pyris-app` writes a low-level `faulthandler` dump (at most 100 threads) for a process that does not run Python code anymore.

### Alerts

Iris sends alerts through [Pushover](https://pushover.net/) when `PYRIS_PUSHOVER_APP_TOKEN` and `PYRIS_PUSHOVER_USER_KEY` are set (for example in the compose env file); `PYRIS_ALERT_NAME` names the instance in the title. Without them, alerts are only logged.

| Event                                                    | Priority   |
| -------------------------------------------------------- | ---------- |
| Self-restart after the watchdog found the process broken | quiet (-1) |
| Restart without a clean shutdown (out of memory or kill) | quiet (-1) |
| Self-restart refused, Iris stays broken                  | urgent (1) |
| Three unexpected restarts within 30 minutes              | urgent (1) |

The container has a memory limit (`PYRIS_MEMORY_LIMIT`, default `6g`), so running out of memory restarts Iris instead of making the host kill other services.
