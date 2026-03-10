# Node Controller

Node Controller manages local model-serving lanes and exposes admin/status APIs.

Backends:
- `ollama` lanes (fixed parallel slots)
- `vllm` lanes (dynamic batching)

## Minimal Startup (Plug-and-Go)

Prerequisites:
- Docker + Docker Compose
- NVIDIA driver on the host (for GPU inference)
- NVIDIA Container Toolkit recommended (for in-container GPU visibility)

Run:

```bash
cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
./start.sh
```

What `./start.sh` does:
- creates `.env` automatically on first run,
- builds an image with bundled `ollama` and `vllm` by default,
- starts the controller and prints backend readiness checks.

Default endpoint: `http://127.0.0.1:8444`

Health check:

```bash
curl -s http://127.0.0.1:8444/health | jq .
```

## Model Storage Default

By default, Ollama models are persisted in Docker named volume `ollama-models`.
To reuse an existing host model directory, set `OLLAMA_MODELS_MOUNT` in `.env`, then rerun `./start.sh`.

## Core APIs

- `GET /health`
- `GET /status`
- `GET /admin/lanes`
- `POST /admin/lanes/apply`
- `GET /admin/lanes/events`
- `GET /admin/lanes/templates`

All endpoints except `/health` and `/` require:

```text
Authorization: Bearer <api_key>
```

API key location: `config.yml` -> `controller.api_key`.

## More Docs

- 2-minute startup guide: `QUICKSTART.md`
- Minimal lane operations and payloads: `LANES.md`
- Benchmark runbook: `TESTING.md`
- CUDA backend notes: `CUDA_BACKEND_SELECTION.md`
- Research/benchmark interpretation: `RESEARCH_SUMMARY.md`
