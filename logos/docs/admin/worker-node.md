---
title: Worker Nodes
---

# Worker nodes

A worker node runs local vLLM models. It opens an outbound connection to the
Logos orchestrator over a secure WebSocket. It does not need an inbound
firewall rule or its own TLS certificate.

1. Register the provider with the Logos API.
2. Save the `provider_id` and the `shared_key` of the provider.
3. On the worker host, go to the worker directory. In a repository checkout,
   run `cd logos/logos-workernode`.
4. Set `LOGOS_URL` and `LOGOS_API_KEY` in the `.env` file of the worker.
5. List the models and the hardware in `config.yml`. Do not put credentials in
   `config.yml`.
6. In the same directory, start the worker with `docker compose up -d`.
7. Make sure that `http://localhost:80/` returns the service information of
   the worker.
8. Check the provider status in the Logos UI.

By default, the production Compose file pulls the worker image
`${REGISTRY}/logos-workernode-vllm` from the public mirror at
`ghcr.io/ls1intum/edutelligence`. No login is necessary. To pull a version tag
from the deployment registry or from your own mirror, set `REGISTRY` and
`IMAGE_TAG` in the `.env` file of the worker. Do this only for that purpose.

To run an image that you built yourself, build it from the worker directory.
The worker directory is the build context. Put the values in the `.env` file
of the worker. Also export the values in the shell, because the Docker CLI
does not read `.env`:

```bash
export REGISTRY=<your-registry> IMAGE_TAG=<tag>
docker build -t "$REGISTRY/logos-workernode-vllm:$IMAGE_TAG" .
```

[The detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
describes registration requests, lane configuration, and troubleshooting.
Apple Silicon nodes use the native MLX setup. `logos-workernode/MACOS.md`
describes this setup.
