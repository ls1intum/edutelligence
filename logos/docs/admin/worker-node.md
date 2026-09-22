---
title: Worker Nodes
---

# Worker nodes

A worker node runs local vLLM models and connects outbound to the Logos
orchestrator over a secure WebSocket. It does not need an inbound firewall
rule or its own TLS certificate.

1. Register the provider with the Logos API and save its `provider_id` and
   `shared_key`.
2. On the worker host, enter the worker directory — from a repository
   checkout, `cd logos/logos-workernode` — and set `LOGOS_URL` and
   `LOGOS_API_KEY` in its `.env`.
3. List the models and hardware in `config.yml`; keep credentials out of it.
4. Start the worker from that directory with `docker compose up -d`.
5. Check that `http://localhost:80/` returns the worker's service info, and
   check the provider status in the Logos UI.

The production Compose file pulls the worker image
`${REGISTRY}/logos-workernode-vllm` from the public mirror at
`ghcr.io/ls1intum/edutelligence` by default — no login required. Set
`REGISTRY` and `IMAGE_TAG` in the worker's `.env` only to pull a version tag
from the deployment registry or from a mirror of your own. To run an image
you built yourself, build it from the worker directory (which is the build
context). Put the values in the worker's `.env` and export them in the shell
as well — the Docker CLI does not read `.env`:

```bash
export REGISTRY=<your-registry> IMAGE_TAG=<tag>
docker build -t "$REGISTRY/logos-workernode-vllm:$IMAGE_TAG" .
```

See [the detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
for registration requests, lane configuration, and troubleshooting. Apple
Silicon nodes use the native MLX setup described in
`logos-workernode/MACOS.md`.
