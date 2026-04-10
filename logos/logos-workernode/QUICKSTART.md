# Quickstart: Logos Worker Node

The worker node connects to the Logos server via a persistent WebSocket connection. It receives inference requests and routes them to its locally managed lanes (Ollama or vLLM).

## 1. Prepare Logos

1. Run the Logos server (e.g., on `http://localhost:18080`).
2. Register a provider with `provider_type=logosnode`.
3. Save the returned `provider_id` and `shared_key`.
4. Add models to that provider in Logos.

## 2. Configure Credentials (.env)

```bash
cp .env.example .env
```

Edit `.env` — only credentials go here:

```ini
LOGOS_URL=http://host.docker.internal:18080
LOGOS_API_KEY=<shared_key from registration>
LOGOS_ALLOW_INSECURE_HTTP=true
```

The server identifies the worker from its API key. No provider_id or worker name needed.

## 3. Configure Hardware (config.yml)

Edit `config.yml` — hardware and tuning settings:

```yaml
worker:
  gpu_poll_interval: 5
  lane_port_start: 11436
  lane_port_end: 11499

logos:
  enabled: true
  capabilities_models:
    - Qwen/Qwen2.5-Coder-7B-Instruct-AWQ
    - model: Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
      tensor_parallel_size: 2

  heartbeat_interval_seconds: 5

engines:
  vllm:
    nccl_debug: WARN
    nccl_debug_subsys: INIT
    model_overrides:
      Qwen/Qwen2.5-Coder-14B-Instruct-AWQ:
        quantization: awq
        disable_custom_all_reduce: true
```

The server decides when to spin up or tear down lanes based on `capabilities_models` and incoming traffic.

> [!NOTE]
> The worker automatically measures each model's VRAM footprint and caches it in the state directory (`/app/data/`). This data is sent to Logos every 5 seconds for VRAM-safe load-balancing.

## 4. Start the Worker

### CPU-only mode (Ollama)
```bash
docker compose -f docker-compose.dev.yml up --build
```

### GPU mode (vLLM)
```bash
docker compose up -d
```

## 5. Verify the Connection

```bash
curl -X POST http://localhost:18080/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```
