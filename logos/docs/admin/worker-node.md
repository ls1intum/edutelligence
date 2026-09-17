---
title: Worker Nodes
---

# Worker nodes

A worker node runs local vLLM models and connects outbound to the Logos
orchestrator over a secure WebSocket. It does not need an inbound firewall
rule or its own TLS certificate.

1. Register the provider with the Logos API and save its `provider_id` and
   `shared_key`.
2. Set `LOGOS_URL` and `LOGOS_API_KEY` in the worker's `.env`.
3. List the models and hardware in `config.yml`; keep credentials out of it.
4. Start the worker with `docker compose up -d`.
5. Check that `http://localhost:80/` returns the worker's service info, and
   check the provider status in the Logos UI. To use a non-default port,
   set `worker.port` in `config.yml` and `WORKER_PORT` in `.env` to the same
   value: the Compose port mapping and health check follow `WORKER_PORT`,
   while the in-container listener is configured separately in `config.yml`.

See [the detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
for registration requests, lane configuration, and troubleshooting. Apple
Silicon nodes use the native MLX setup described in
`logos-workernode/MACOS.md`.
