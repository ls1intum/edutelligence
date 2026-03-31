# Quickstart: Logos Worker Node

The worker node connects to the Logos server via a persistent WebSocket connection. It receives inference requests and routes them to its locally managed lanes (Ollama or vLLM).

## 1. Prepare Logos

1. Run the Logos server (e.g., on `http://localhost:18080`).
2. Register a provider with `provider_type=logosnode`.
3. Save the returned `provider_id` and `shared_key`.
4. Add models to that provider in Logos.

## 2. Configure the Worker Environment

To start, copy the provided `.env.example` to `.env`:
```bash
cp .env.example .env
```

Now, edit your new `.env` file to configure network bindings and deployment options:

### A. Essential Connection Settings
Define how the worker connects to the main Logos server:
*   `LOGOS_URL`: The URL of the Logos Server (e.g., `http://host.docker.internal:18080` for local or `https://...` for prod).
*   `LOGOS_PROVIDER_ID`: The numeric ID you got when registering the provider in Logos.
*   `LOGOS_API_KEY`: The `shared_key` you got during registration.
*   `LOGOS_ALLOW_INSECURE_HTTP`: Must be `true` if your `LOGOS_URL` uses `http://` (Local dev only).

### B. Port Mapping (Crucial for Local Dev)
By default, the worker is configured to bind strictly to localhost (`127.0.0.1`) on standard HTTP port **`80`**.

If you are running the Logos Server (or Traefik proxy) on the *same physical machine*, port `80` will conflict and the worker will fail to start.

**For local development on the same machine:**
Change `WORKER_PORT` in your `.env` to an unused port:
```ini
WORKER_PORT=8444
```
This maps the internal container port to `127.0.0.1:8444` on your host.

### C. Advanced `.env` Overrides (Optional)
The Docker Compose build process reads these overrides dynamically. You rarely need to touch them unless making deep architecture changes:

*   `PYTHON_IMAGE`: Base image for CPU (default: `python:3.12-slim`).
*   `CUDA_IMAGE`: Base image for GPU (default: `nvidia/cuda:13.1.0...`).
*   `INSTALL_VLLM`: Set to `0` to skip vLLM (default 1 in GPU, 0 in CPU).
*   `INSTALL_OLLAMA`: Set to `0` to skip Ollama (default 1).
*   `VLLM_PIP_SPEC`: Override the specific PyTorch/vLLM architecture wheel installed.

## 3. Define AI Capabilities (`config.yml`)

The worker does **not** statically define lanes. Instead, it declares a set of `capabilities_models` to the master Logos Capacity Planner. The server decides when to spin up or tear down lanes based on incoming request traffic.

Open `config.yml` and declare which models this worker is allowed/capable of running under the `logos.capabilities_models` list. 

You can provide hardware hints (like `tensor_parallel_size`, `kv_budget_mb`, `max_context_length`) which the Logos server will honor when it commands the worker to wake up a model:

```yaml
logos:
  enabled: true
  # Connection credentials are loaded from environment variables.
  # Set LOGOS_URL, LOGOS_PROVIDER_ID, LOGOS_API_KEY, LOGOS_WORKER_NODE_ID in .env.
  
  capabilities_models:
    # Example 1: GPU model with specific bounds
    - model: Qwen/Qwen2.5-Coder-7B-Instruct-AWQ
      tensor_parallel_size: 1
      kv_budget_mb: 2048
      max_context_length: 4096
      
    # Example 2: Larger GPU model spanning multiple GPUs
    - model: Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
      tensor_parallel_size: 2
      kv_budget_mb: 2048
      max_context_length: 4096
      
    # Example 3: Simple string declaration (relies on Logos server defaults)
    - llama3.1:8b

  heartbeat_interval_seconds: 5
```

> [!NOTE] 
> The worker automatically measures each model's VRAM footprint the first time it loads, and caches it in `model_profiles` at the bottom of your `config.yml`. This empirical data is sent to the Logos Server every 5 seconds so the capacity planner makes VRAM-safe load-balancing decisions.

## 4. Choose a Deployment Mode

The worker requires different Docker configurations depending on whether you want a lightweight CPU-only Ollama setup or a full CUDA-enabled vLLM setup.

### Mode A: Lightweight CPU-only (Ollama)
**Best for local development without an Nvidia GPU.**

*   **Configured via:** `.env` and `docker-compose.yml`
*   **Default Base Image:** `python:3.12-slim`
*   **Behavior:** Installs Ollama into a lightweight Python container. No vLLM or CUDA drivers.

### Mode B: Full GPU with vLLM (Nvidia)
**Required for production vLLM lanes.**

*   **Configured via:** `.env` and `docker-compose.gpu.yml`
*   **Default Base Image:** `nvidia/cuda:13.1.0-cudnn-devel-ubuntu24.04`
*   **Behavior:** Pulls the large CUDA image, installs PyTorch/vLLM, configures NCCL and shared memory, and passes GPUs to the container.

## 5. Start the Worker

The `start.sh` wrapper script simplifies launching the correct Docker Compose setup.

### Start in CPU-only mode (Mode A)
```bash
./start.sh
```
This uses `docker-compose.yml`.

### Start in GPU mode (Mode B)
```bash
./start.sh --gpu
```
This uses *both* `docker-compose.yml` and `docker-compose.gpu.yml` to override the base image and add GPU configurations.

## 6. Verify the Connection

The worker runs headlessly — there is no management HTTP API or web UI exposed on the worker port (`WORKER_PORT`), only a simple `/` info endpoint and healthcheck.

To verify the connection, call the Logos Server:

```bash
# Ask the Logos Server for the provider status
curl -X POST http://localhost:18080/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```

A healthy response contains the worker's reported state (via the WebSocket bridge):
- `worker_id`
- `runtime.devices`
- `runtime.capacity`
- `runtime.lanes`


