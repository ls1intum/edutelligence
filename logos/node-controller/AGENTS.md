# AGENTS.md — Node Controller Project Guide for AI Agents

## Project Overview

**Node Controller** is a lightweight management daemon that runs alongside a single Ollama Docker container on a GPU node. It provides:

- **Ollama container lifecycle**: create, start, stop, restart, reconfigure (recreate with new params), destroy
- **nvidia-smi GPU metrics**: real utilization %, temperature, power, per-GPU VRAM
- **Ollama status**: loaded models, available models, VRAM per model, version
- **Model operations**: pull (blocking + streaming), delete, unload from VRAM, preload into VRAM, create variants via Modelfile, show model details, copy/alias
- **Logos integration**: single `/status` endpoint for Logos SDI to poll instead of hitting Ollama directly

**Key design principle**: The controller manages but does NOT proxy requests. Ollama's port is published directly to the host. Clients (including Logos) send inference requests straight to the Ollama container. The controller is only for management, monitoring, and configuration.

## Tech Stack

- **Language**: Python 3.13
- **Framework**: FastAPI + Uvicorn
- **Docker management**: Docker SDK for Python (`docker` package)
- **HTTP Client**: httpx (async, single shared client)
- **Config**: YAML file (`config.yml`) with Pydantic v2 models
- **GPU metrics**: subprocess calls to `nvidia-smi`
- **Testing**: pytest + pytest-asyncio (40 tests)

## Repository Structure

```
node-controller/
├── AGENTS.md                              # This file
├── config.yml                             # Runtime config (controller + Ollama + Docker)
├── docker-compose.yml                     # Compose for the controller container
├── docker-compose.gpu.yml                 # GPU overlay (add nvidia-smi + NVML mounts)
├── Dockerfile                             # Multi-stage build, runs as root (Docker socket)
├── requirements.txt                       # Python dependencies (6 packages)
├── pytest.ini                             # Test config (asyncio_mode = auto)
├── .env.example                           # Environment variables template
├── .dockerignore                          # Build context exclusions
├── Node_Controller.postman_collection.json # Postman v2.1 collection for testing
├── node_controller/
│   ├── __init__.py                        # Package marker
│   ├── main.py              (191 lines)   # FastAPI app, lifespan, uvicorn entry point
│   ├── auth.py              (55 lines)    # Bearer token auth via Depends()
│   ├── config.py            (147 lines)   # YAML load/save, apply_reconfigure, _RESTART_FIELDS
│   ├── models.py            (240 lines)   # All Pydantic models (config, status, API req/resp)
│   ├── gpu.py               (161 lines)   # nvidia-smi background poller
│   ├── ollama_manager.py    (460 lines)   # Docker SDK container lifecycle + model operations
│   ├── ollama_status.py     (190 lines)   # /api/ps + /api/tags background poller (parallel)
│   ├── logos_api.py         (87 lines)    # Logos-facing status endpoints
│   └── admin_api.py         (385 lines)   # Admin management + model customization endpoints
└── tests/
    └── test_node_controller.py (600 lines) # 40 unit tests
```

**Total source**: ~1,916 lines across 9 modules + 1 test file.

## Architecture

### Two Products, Clearly Separated

1. **Node Controller** (this project) — management daemon, runs in its own container
2. **Ollama Server** — standard `ollama/ollama` Docker image, created dynamically by the controller

```
┌─────────────────────────────────────────────────────────┐
│  GPU Node                                                │
│                                                          │
│  ┌──────────────────┐     Docker SDK     ┌────────────┐ │
│  │ Node Controller  │ ─── manages ────── │  Ollama    │ │
│  │ :8443            │                    │  :11434    │ │
│  │  - admin API     │ ── httpx polls ──▶ │  (direct)  │ │
│  │  - GPU metrics   │                    │            │ │
│  │  - status API    │                    │            │ │
│  └──────────────────┘                    └────────────┘ │
│         ▲                                      ▲        │
└─────────┼──────────────────────────────────────┼────────┘
          │ management/status                    │ inference
    ┌─────┴──────┐                         ┌─────┴───────┐
    │   Logos    │                         │   Logos     │
    │   (SDI)   │                         │  (Executor) │
    └────────────┘                         └─────────────┘
```

### Request Flow

- **Inference**: `Logos Executor → Ollama :11434` (direct, no controller involved)
- **Status polling**: `Logos SDI → Controller /status` → returns GPU + Ollama + config data
- **Admin ops**: `Admin → Controller /admin/*` → Docker SDK → Ollama container lifecycle

### Authentication

All endpoints except `/health` and `/` require `Authorization: Bearer <api_key>`. Auth uses FastAPI `Depends()` — NOT middleware — avoiding Starlette `BaseHTTPMiddleware` performance overhead.

### Config Management

`config.yml` is the single source of truth. Changes via `/admin/ollama/reconfigure`:

1. Compares submitted values against current config — **only actually-changed fields** are reported
2. If no values differ → returns `"No changes detected"` immediately (no disk write, no restart)
3. If changed fields are in `_RESTART_FIELDS` → container is recreated with new env vars
4. If changed fields are NOT in `_RESTART_FIELDS` → config saved, no restart
5. Config is written directly with `os.fsync()` (not temp+rename — bind-mounted files can't be renamed)

### Concurrency Safety

- **`asyncio.Lock`** on `recreate()` prevents two concurrent reconfigure calls from racing
- **Preload tasks** are tracked in `_preload_tasks` list and cancelled on shutdown
- **Status poller** fires `/api/version`, `/api/ps`, `/api/tags` in parallel via `asyncio.gather`
- **Readiness check** uses exponential backoff (100ms → 2s cap) instead of fixed 1s sleep

## File-by-File Guide

### `main.py` — Application Entry Point
- Creates the FastAPI app, wires lifespan (startup/shutdown)
- Startup: load config → connect Docker → create/start Ollama → start GPU poller → start status poller
- Stores all services in `app.state` for route handlers
- Supports optional TLS via config

### `auth.py` — Authentication
- `verify_api_key()` — FastAPI dependency, validates `Authorization: Bearer <key>` against `config.controller.api_key`
- Uses `hmac.compare_digest()` for timing-safe comparison
- Returns 401 (missing), 403 (invalid)

### `config.py` — Configuration Management
- `load_config()` — loads YAML with fallback chain: arg → env var → `./config.yml` → `../config.yml` → defaults
- `save_config()` — direct write + `os.fsync()` (bind-mount safe)
- `apply_reconfigure()` — returns `(new_config, needs_restart, actually_changed_fields)` 3-tuple
- `_RESTART_FIELDS` — frozenset of 22 fields that require container recreation

### `models.py` — Pydantic Models
- `OllamaConfig` — all Ollama runtime params (num_parallel, keep_alive, flash_attention, kv_cache_type, sched_spread, multiuser_cache, gpu_overhead_bytes, load_timeout, origins, noprune, etc.)
- `ControllerConfig` — port, API key, TLS, poll intervals
- `DockerConfig` — network name, volume name
- `ContainerStatus`, `OllamaStatus`, `GpuSnapshot`, `NodeStatus` — status models
- `ReconfigureRequest` — partial update (all fields optional)
- `ModelCreateRequest` — name + Modelfile content for model variants
- `ModelInfoResponse` — detailed model info from `/api/show`
- `ActionResponse`, `HealthResponse` — generic API responses

### `ollama_manager.py` — Container Lifecycle (Docker SDK)
- `create()` — remove existing → build env + device_requests → `containers.run()` → wait for ready → fire preloads
- `recreate()` — locked (`asyncio.Lock`) → force-remove → create with new config
- `start()`, `stop()`, `restart()`, `destroy()` — basic lifecycle
- `pull_model()` — blocking pull, `pull_model_streaming()` — NDJSON streaming progress
- `create_model()` — Modelfile-based variant creation (custom num_ctx, temperature, system prompt)
- `show_model()`, `copy_model()`, `delete_model()`, `unload_model()`, `preload_model()`
- Volume mount uses `config.models_path` (not hardcoded), sets `OLLAMA_MODELS` env var to match
- `_build_env()` — maps all OllamaConfig fields to `OLLAMA_*` env vars; `env_overrides` applied last
- `_build_device_requests()` — `"none"` = CPU, `"all"` = all GPUs, `"0,1"` = specific IDs
- `_wait_for_ready()` — exponential backoff from 100ms
- `close()` — cancels in-flight preload tasks before releasing clients

### `ollama_status.py` — Background Poller
- Polls Ollama's `/api/version`, `/api/ps`, `/api/tags` concurrently via `asyncio.gather`
- Caches latest `OllamaStatus` behind `asyncio.Lock`
- `update_config()` — called after reconfigure to retarget the poller

### `gpu.py` — GPU Metrics Collector
- Polls `nvidia-smi --query-gpu` as subprocess at configurable interval
- Parses CSV into `GpuInfo` objects (index, uuid, name, memory, utilization, temp, power)
- Degrades gracefully when nvidia-smi not found (sets `available=False`)

### `logos_api.py` — Logos-Facing Endpoints
- `GET /status` — combined snapshot (container + Ollama + GPU + config) — the primary Logos poll target
- `GET /gpu` — GPU metrics only
- `GET /models` — available + loaded models
- `GET /config` — current Ollama runtime config

### `admin_api.py` — Admin Endpoints
- Container lifecycle: `start`, `stop`, `restart`, `reconfigure`, `destroy`
- Model operations: `pull`, `pull/stream` (NDJSON), `delete`, `unload`, `preload`
- Model customization: `create` (Modelfile), `show` (inspect), `copy` (alias)
- `reconfigure` detects no-op (all values match) and returns immediately without restart
- All Docker errors caught as HTTP 502

## API Endpoints

### Logos-facing (authenticated)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Full node status (container + Ollama + GPU + config) |
| GET | `/gpu` | GPU metrics only |
| GET | `/models` | Available + loaded models |
| GET | `/config` | Current Ollama runtime config |

### Admin — Container Lifecycle (authenticated)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/ollama/start` | Start/create the Ollama container |
| POST | `/admin/ollama/stop` | Gracefully stop |
| POST | `/admin/ollama/restart` | Restart without config change |
| POST | `/admin/ollama/reconfigure` | Update config + recreate if needed |
| POST | `/admin/ollama/destroy` | Force-remove container |

### Admin — Model Operations (authenticated)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/models/pull` | Download a model (blocking) |
| POST | `/admin/models/pull/stream` | Download with NDJSON progress |
| POST | `/admin/models/delete` | Delete a model from disk |
| POST | `/admin/models/unload` | Unload model from VRAM |
| POST | `/admin/models/preload` | Preload model into VRAM |
| POST | `/admin/models/create` | Create variant from Modelfile |
| POST | `/admin/models/show` | Inspect model details |
| POST | `/admin/models/copy` | Copy/alias a model |

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check for Docker/load balancer |
| GET | `/` | Service info |

## Ollama Config Fields

All fields in `OllamaConfig` that become `OLLAMA_*` environment variables:

| Config Field | Env Var | Requires Restart | Default |
|-------------|---------|-----------------|---------|
| `num_parallel` | `OLLAMA_NUM_PARALLEL` | Yes | 4 |
| `max_loaded_models` | `OLLAMA_MAX_LOADED_MODELS` | Yes | 3 |
| `keep_alive` | `OLLAMA_KEEP_ALIVE` | Yes | "5m" |
| `max_queue` | `OLLAMA_MAX_QUEUE` | Yes | 512 |
| `context_length` | `OLLAMA_CONTEXT_LENGTH` | Yes | 4096 |
| `flash_attention` | `OLLAMA_FLASH_ATTENTION` | Yes | true |
| `kv_cache_type` | `OLLAMA_KV_CACHE_TYPE` | Yes | "q8_0" |
| `sched_spread` | `OLLAMA_SCHED_SPREAD` | Yes | false |
| `multiuser_cache` | `OLLAMA_MULTIUSER_CACHE` | Yes | false |
| `gpu_overhead_bytes` | `OLLAMA_GPU_OVERHEAD` | Yes | 0 |
| `load_timeout` | `OLLAMA_LOAD_TIMEOUT` | Yes | "" |
| `origins` | `OLLAMA_ORIGINS` | Yes | [] |
| `noprune` | `OLLAMA_NOPRUNE` | Yes | false |
| `models_path` | `OLLAMA_MODELS` | — | "/root/.ollama/models" |
| `gpu_devices` | (Docker device_requests) | Yes | "all" |
| `image` | (Docker image tag) | Yes | "ollama/ollama:latest" |
| `host_port` | (Docker port mapping) | Yes | 11434 |
| `env_overrides` | (merged last, overrides all) | Yes | {} |
| `preload_models` | (fire-and-forget after create) | No | [] |

## Testing

```bash
cd node-controller
pip install -r requirements.txt
pip install pytest pytest-asyncio
pytest -v     # 40 tests, ~0.3s
```

## Running

```bash
# Local
cd node-controller && pip install -r requirements.txt
python -m node_controller.main

# Docker (CPU)
docker compose up --build

# Docker (GPU)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

## Key Design Decisions

1. **Single Ollama container** (not multi-lane): eliminates proxy complexity, reduces VRAM waste from duplicate CUDA contexts
2. **No request proxying**: controller manages, doesn't proxy. Ollama port published directly.
3. **Logos pulls from controller** (not push): simpler, no bidirectional dependency
4. **Direct file write + fsync** (not temp+rename): bind-mounted files can't be renamed (EBUSY)
5. **Runs as root**: Docker socket access = host root anyway (Portainer/Watchtower pattern)
6. **asyncio.Lock on recreate**: prevents concurrent reconfigure races
7. **Preload tasks tracked**: cancelled on shutdown, cleaned from list when done
8. **Parallel status polling**: 3 Ollama API calls fired concurrently, not sequentially
9. **Exponential backoff for readiness**: 100ms start, 2s cap — detects ready ~850ms faster than 1s polling
10. **No-op reconfigure detection**: same values = no restart, no disk write, honest response
11. **`env_overrides` applied last**: always overrides computed values
