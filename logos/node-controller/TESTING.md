# Node Controller and Ollama Testing Guide

This guide covers how to validate the Node Controller API and the managed Ollama container.

## Prerequisites

- Docker and Docker Compose installed.
- Current host ports: controller `8444` (set by `CONTROLLER_PORT` in `.env` or compose), Ollama `11435` (from `config.yml`).
- Config file: `config.yml` in this folder.
- Optional environment file: copy `.env.example` to `.env` and set `CONTROLLER_PORT` if needed.

## Quick start

1. (Optional) Set a real API key in `config.yml`:

   ```yaml
   controller:
     api_key: YOUR_RANDOM_SECRET
   ```

2. Start the controller:

   ```bash
   sudo docker compose up --build
   ```

3. Confirm the controller is up:

   ```bash
  curl -s http://localhost:8444/health | jq .
   ```

   Expected fields: `status`, `ollama_running`, `gpu_available`.

## Troubleshooting: port 11434 already in use

If you see an error like `failed to bind host port 0.0.0.0:11434`, keep the host Ollama service running and remap the container port.

1. Confirm the port is taken:

   ```bash
   sudo ss -ltnp | grep ':11434'
   ```

2. Change the Node Controller's published port in `config.yml`:

   ```yaml
   ollama:
     host_port: 11435
   ```

3. Restart the controller so the new port mapping is applied:

```bash
sudo docker compose up -d --build
```

## Controller API tests

All endpoints except `/health` require a Bearer token. Export it once:

```bash
export API_KEY=YOUR_RANDOM_SECRET
```

### Health check (no auth)

```bash
curl -s http://localhost:8444/health | jq .
```

### Status endpoints (auth required)

```bash
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8444/status | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8444/gpu | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8444/models | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8444/config | jq .
```

### Ollama container lifecycle (auth required)

```bash
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://localhost:8444/admin/ollama/start | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://localhost:8444/admin/ollama/stop | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://localhost:8444/admin/ollama/restart | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://localhost:8444/admin/ollama/destroy | jq .
```

### Reconfigure (auth required)

Example: change `num_parallel` and `max_loaded_models`:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"num_parallel":2,"max_loaded_models":1}' \
  http://localhost:8444/admin/ollama/reconfigure | jq .
```

### Model operations (auth required)

Pull a model:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b"}' \
  http://localhost:8444/admin/models/pull | jq .
```

Unload a model from VRAM:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b"}' \
  http://localhost:8444/admin/models/unload | jq .
```

Preload a model into VRAM:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b"}' \
  http://localhost:8444/admin/models/preload | jq .
```

Create a model variant from a Modelfile:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"qwen2.5:0.5b-8k","modelfile":"FROM qwen2.5:0.5b\nPARAMETER num_ctx 8192"}' \
  http://localhost:8444/admin/models/create | jq .
```

Show model details:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b"}' \
  http://localhost:8444/admin/models/show | jq .
```

Copy a model:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b","destination":"qwen2.5:0.5b-alias"}' \
  http://localhost:8444/admin/models/copy | jq .
```

Stream pull progress (NDJSON):

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b"}' \
  http://localhost:8444/admin/models/pull/stream
```

## Ollama container tests (direct API)

The controller publishes Ollama on the configured host port. Default is `11434`.
If you remapped it, replace `11434` with your `host_port` (example: `11435`).

List models:

```bash
curl -s http://localhost:11434/api/tags | jq .
```

Generate a response (non-streaming):

```bash
curl -s http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b","prompt":"Say hello in one sentence.","stream":false}' | jq .
```

Check running container logs:

```bash
sudo docker logs ollama-server
```

## Postman

You can import `Node_Controller.postman_collection.json` and set the base URL and API key in the collection variables.

## Notes

- If TLS is enabled in `config.yml`, use `https://` and provide valid certs in `certs/`.
- GPU metrics will be unavailable if `nvidia-smi` is not installed on the host.
- The controller listens on port `8443` inside the container. Use `CONTROLLER_PORT` to choose the host port (currently `8444`).

### GPU metrics troubleshooting

If `/gpu` returns `nvidia_smi_available: true` but the GPU list is empty, the container can run `nvidia-smi` but cannot see GPU device nodes. Make sure the host has NVIDIA Container Toolkit installed and start with the GPU overlay:

```bash
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Then verify inside the container:

```bash
sudo docker exec node-controller nvidia-smi -L
sudo docker exec node-controller ls -l /dev/nvidia*
```


## Port forwarding guide (customized for your setup)

You asked for a fool proof workflow that feels local. The easiest is VS Code Remote SSH port forwarding. This keeps the host Ollama service untouched while letting your local app talk to the controller and the managed Ollama container.

### 1. Pick free local ports

Run this on your **local machine** (not the server) and pick two free ports:

```bash
python3 - <<'PY'
import socket

def free_port():
  s = socket.socket()
  s.bind(('', 0))
  port = s.getsockname()[1]
  s.close()
  return port

print('Free port A:', free_port())
print('Free port B:', free_port())
PY
```

Write them down as:

- `LOCAL_CONTROLLER_PORT` (maps to remote `8444`)
- `LOCAL_OLLAMA_PORT` (maps to remote `11435`)

Example:

```
LOCAL_CONTROLLER_PORT=18444
LOCAL_OLLAMA_PORT=11435
```

### 2. Forward ports with VS Code Remote SSH (recommended)

1. Connect to the server via VS Code Remote SSH.
2. Open the Ports view (Remote Explorer -> Ports).
3. Add two forwarded ports:
   - Local `LOCAL_CONTROLLER_PORT` -> Remote `8444`
   - Local `LOCAL_OLLAMA_PORT` -> Remote `11435`
4. Set both to **Local** (not Public).

### 3. Verify from your local machine

Controller health:

```bash
curl -s http://localhost:LOCAL_CONTROLLER_PORT/health | jq .
```

Ollama tags (direct):

```bash
curl -s http://localhost:LOCAL_OLLAMA_PORT/api/tags | jq .
```

### 4. Use in your local app

Point your app to:

- Controller base URL: `http://localhost:LOCAL_CONTROLLER_PORT`
- Ollama base URL: `http://localhost:LOCAL_OLLAMA_PORT`

### Optional: plain SSH port forwarding (if you prefer CLI)

From your local machine:

```bash
ssh -L LOCAL_CONTROLLER_PORT:localhost:8444 \
  -L LOCAL_OLLAMA_PORT:localhost:11435 \
  ge84ciq@hochbruegge.aet.cit.tum.de
```

Keep that SSH session open while you test. Then use the same local URLs as above.
