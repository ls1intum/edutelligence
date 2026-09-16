---
title: Operations and Troubleshooting
---

# Operations and troubleshooting

Inspect service logs with:

```bash
docker compose --env-file .env logs -f logos-orchestrator
docker compose --env-file .env logs -f logos-webservice
```

The UI, Swagger API, and completion API share the HTTPS endpoint. A `404`
from `GET /v1` is expected; use `/docs` for Swagger. If browser POST or
WebSocket requests fail while GET requests work, check
`LOGOS_CORS_ALLOWED_ORIGINS`.

For worker connection failures, confirm that `LOGOS_URL` uses `https://`, the
shared key matches the registered provider, and the worker can resolve and
reach the orchestrator. For model failures, check provider permissions,
available lanes, and the worker's `/admin/runtime` endpoint.

Disable the capacity planner only when diagnosing scheduling behavior:

```yaml
LOGOS_CAPACITY_PLANNER_ENABLED: "false"
```
