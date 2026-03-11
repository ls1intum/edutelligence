# Logos Node Provider Setup and Verification

This runbook shows how to:

- register a node provider in Logos,
- connect models/profile permissions,
- configure the node runtime,
- verify status and lane control,
- send an inference request through Logos to node lanes.

## 1. Architecture and Flow

Canonical provider type is `node` (the old `node_controller` paths are deprecated aliases).

1. Admin registers provider in Logos (`/logosdb/providers/node/register`).
2. Logos stores `provider_id` + generated `shared_key` in DB.
3. Node starts with `logos.enabled=true` and calls `/logosdb/providers/node/auth` using `provider_id` + `shared_key`.
4. Logos returns short-lived `session_token` + `wss://.../logosdb/providers/node/session`.
5. Node opens persistent secure websocket and sends heartbeat/status updates (GPU + lanes).
6. Logos backend APIs send lane commands over websocket RPC (`apply/sleep/wake/reconfigure/delete`).
7. For `/v1/chat/completions`, Logos selects least-loaded running replica lane and offloads via websocket RPC `infer`/`infer_stream`.

## 2. Prerequisites

- Logos reachable via HTTPS (`https://...`) so node can use `wss://...`.
- Valid root `logos_key`.
- Node runtime available (GPU drivers / Ollama or vLLM as needed).
- At least one model in Logos DB linked to the node provider.

Notes:

- Node auth/session endpoints enforce TLS semantics (`https` / `wss`).
- Node bridge currently validates TLS certificates. Use a trusted cert chain (or trust your internal CA in the node environment).

Development-only override:

- Logos: set env `LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP=true`
- Node config: set `logos.allow_insecure_http: true`
- Then `logos.logos_url` may use `http://...` and websocket upgrades use `ws://...`.

## 3. Logos Preconfiguration (DB-side)

You need all of these before inference works:

1. Register provider:
- `POST /logosdb/providers/node/register`
- returns `provider_id`, `shared_key`

2. Link model to provider:
- `POST /logosdb/connect_model_provider`
- body needs `logos_key`, `model_id`, `provider_id`

3. Ensure profile can use the model:
- `POST /logosdb/connect_profile_model`
- body needs `logos_key`, `profile_id`, `model_id`

4. (Optional) create/select profile:
- `POST /logosdb/add_profile`
- `POST /logosdb/get_process_id`

## 4. Node Configuration

Edit `node-controller/config.yml`:

```yaml
controller:
  port: 8444
  api_key: "replace-node-admin-api-key"
  tls_enabled: false

logos:
  enabled: true
  logos_url: "https://localhost:8080"
  allow_insecure_http: false
  provider_id: 41
  shared_key: "paste-shared-key-from-register-response"
  node_id: "node-gpu-1"
  capabilities_models:
    - "qwen2.5-coder:32b"
  heartbeat_interval_seconds: 5
  reconnect_backoff_seconds: 3

lanes:
  - lane_id: "qwen-32b-r1"
    model: "qwen2.5-coder:32b"
    backend: "ollama"
    num_parallel: 4
    context_length: 4096
    gpu_devices: "0"
  - lane_id: "qwen-32b-r2"
    model: "qwen2.5-coder:32b"
    backend: "ollama"
    num_parallel: 4
    context_length: 4096
    gpu_devices: "1"
```

Key points:

- `logos.provider_id` and `logos.shared_key` must match the provider row created by Logos.
- Replica lanes are supported via unique `lane_id` values.
- `capabilities_models` limits what models this node will serve (intersection with DB deployment assignment).
- `logos.allow_insecure_http` must stay `false` outside local development.

## 5. Bring Up Services

From `edutelligence/logos`:

```bash
docker compose up -d logos-db logos-server traefik
```

From `edutelligence/logos/node-controller`:

```bash
./start.sh
```

The node will automatically:

1. call `/logosdb/providers/node/auth`,
2. open websocket session,
3. publish status updates.

## 6. Verify Runtime Connectivity

Use Logos backend endpoints (root key required):

1. `POST /logosdb/providers/node/status`
2. `POST /logosdb/providers/node/gpu`
3. `POST /logosdb/providers/node/lanes`

Expected:

- `status.last_heartbeat` updates regularly.
- `status.lanes[*].runtime_state` should be `running` for active lanes.

## 7. Verify Lane Control

Use these APIs (root key required):

1. `POST /logosdb/providers/node/lanes/apply`
2. `POST /logosdb/providers/node/lanes/sleep`
3. `POST /logosdb/providers/node/lanes/wake`
4. `POST /logosdb/providers/node/lanes/reconfigure`
5. `POST /logosdb/providers/node/lanes/delete`

If websocket session is stale/disconnected, Logos returns `503`.

## 8. Verify Inference Offload

Send request via Logos:

```bash
curl -k -sS "https://localhost:8080/v1/chat/completions" \
  -H "Authorization: Bearer <logos_key>" \
  -H "use_profile: <profile_id>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:32b",
    "stream": false,
    "messages": [{"role":"user","content":"Say hello from node lanes."}]
  }'
```

Routing behavior:

- Logos chooses among running replicas of the same model by lowest `active_requests`.
- If no eligible running lane exists, request fails with `503`.

## 9. Quick Troubleshooting

- `400 TLS is required for node provider auth/session endpoints`:
  Logos is being called over plain HTTP or proxy headers are not set correctly.
- `403 Invalid provider shared key`:
  `provider_id/shared_key` mismatch between node config and Logos DB.
- `503 No node session for provider` or `Node session is stale`:
  node websocket is not connected or heartbeat not arriving.
- `503 no active eligible lane` on inference:
  lane not running, model not in `capabilities_models`, or model not linked in DB.
