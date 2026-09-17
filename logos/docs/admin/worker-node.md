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
   check the provider status in the Logos UI.

The production Compose file pulls the worker image
`${REGISTRY}/logos-workernode-vllm`. As with the main stack, the build
workflow publishes it to the project's Harbor registry (team-internal) —
see the [installation guide](installation.md) for the `REGISTRY`/`IMAGE_TAG`
and login setup. Without access to that registry, build it locally from the
repository root and set the matching `REGISTRY`/`IMAGE_TAG` in the worker's
`.env`:

```bash
docker build -t "$REGISTRY/logos-workernode-vllm:$IMAGE_TAG" logos/logos-workernode
```

See [the detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
for registration requests, lane configuration, and troubleshooting. Apple
Silicon nodes use the native MLX setup described in
`logos-workernode/MACOS.md`.
