---
title: Operations and Troubleshooting
---

# Operations and troubleshooting

To read the service logs, use these commands:

```bash
docker compose --env-file .env logs -f logos-orchestrator
docker compose --env-file .env logs -f logos-webservice
```

The UI, the Swagger API, and the completion API use the same HTTPS endpoint.
A `404` from `GET /v1` is normal. Use `/docs` for Swagger. If browser POST or
WebSocket requests fail but GET requests work, check
`LOGOS_CORS_ALLOWED_ORIGINS`.

If a worker cannot connect, make sure of these items:

- `LOGOS_URL` uses `https://`.
- The shared key is the same as the key of the registered provider.
- The worker can resolve the name of the orchestrator and can reach it.

If a model fails, check the provider permissions and the available lanes.
Also check the runtime status of the worker. Use the Logos UI, or use the
`POST /logosdb/providers/logosnode/status` endpoint of the orchestrator (see
the worker node guide).

Disable the capacity planner only to find the cause of a scheduling problem:

```yaml
LOGOS_CAPACITY_PLANNER_ENABLED: "false"
```
