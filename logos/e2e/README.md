# Logos E2E

An end-to-end suite that runs without GPUs, in four tiers.

| Tier | What it drives | Needs | Runtime |
|------|----------------|-------|---------|
| 1 — `tests/gpu` | The real `logos_worker_node` against simulated GPUs | nothing | ~75 s |
| 2 — `tests/node` | Orchestrator + database + simulated worker nodes | Docker | minutes |
| 3 — `tests/client` | The same stack through the real OpenAI/Anthropic SDKs | Docker | minutes |
| 4 — `../logos-ui/e2e` | The UI in a real browser (Playwright) | Docker + Node | minutes |

Nothing in the worker or the orchestrator is stubbed. Only the layer *below* the
worker is simulated — `nvidia-smi`, `nvcc`, the `vllm` binary — because that is
where every GPU-compatibility decision is actually read from.

## Quick start

```bash
cd logos/e2e
uv venv .venv && uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python -r ../logos-workernode/requirements.txt

# Tier 1 — no Docker
.venv/bin/python -m pytest tests/gpu -v

# Tiers 2 and 3
.venv/bin/python -m harness.stack.compose up
.venv/bin/python -m pytest tests/node tests/client -v
.venv/bin/python -m harness.stack.compose down

# Tier 4 — adds Keycloak, the webservice and the UI
.venv/bin/python -m harness.stack.compose up --ui
cd ../logos-ui && npm ci && npx playwright install chromium && npm run e2e
```

The stack is started separately on purpose. A suite that owns the lifecycle
rebuilds images on every run and tears down the evidence at the moment a failure
needs inspecting. With the stack down, the Tier 2/3 tests skip with the command
to start it.

The `--ui` profile roughly triples startup time (a Keycloak boot and an Angular
production build), which is why the inter-node and SDK tiers run without it.
Playwright goes through Traefik rather than straight at the UI container: in
production the UI and the API share an origin, and testing them on separate
origins would miss every CORS, cookie and same-origin-WebSocket problem that
shape causes.

## Why a GPU-less suite can test GPU compatibility

Every GPU decision in the worker is mediated by a text boundary the simulator
owns:

| Decision | Read from | Simulated by |
|---|---|---|
| Attention backend, `TORCH_CUDA_ARCH_LIST` | `nvidia-smi --query-gpu=compute_cap` | `gpusim/bin/nvidia-smi` |
| VRAM, telemetry, degraded and `ERR!` fields | `nvidia-smi --query-gpu=…` | same, driven by a state file |
| Stuck CUDA contexts | `nvidia-smi --query-compute-apps` | the state file's VRAM ledger |
| nvcc / C-compiler preflight | `shutil.which`, `CUDA_HOME` | which shims are installed on `PATH` |
| Fatal CUDA, cache poisoning, broken shards | the vLLM log blob | the replayed corpus |
| Lane liveness, sleep/wake, metrics | HTTP to the lane | `gpusim/server.py` |

The VRAM ledger is what makes this more than canned output: the fake vLLM debits
its `--gpu-memory-utilization` share on startup and credits it back on a clean
exit, so the capacity planner watches memory actually move — and a scripted
`leak_vram` reproduces a stuck CUDA context exactly as the worker detects one.

## What this suite cannot catch

Stated plainly, because a suite that hides its blind spots is worse than one
that has them:

- Numerical or kernel-level errors. Nothing here runs a kernel.
- The real OOM threshold at a given `gpu_memory_utilization`. The simulator's
  arithmetic is the worker's arithmetic, not the allocator's.
- Actual NCCL behaviour at TP > 1 — ring setup, transport selection, hangs.
- Driver-level events: Xid errors, GSP RPC failures, PCIe drops. Their
  *symptoms* are simulated; their occurrence is not.
- Throughput, TTFT, and anything else timing-dependent.
- A vLLM upgrade that breaks real kernels while keeping its CLI and log wording.

There is currently no GPU runner available, so the mitigation is
calibration-by-artifact rather than hardware:

1. **The corpus grows from production.** Every GPU incident lands a log file in
   `harness/corpus/` in the same PR as its fix, with `source` naming where the
   log came from. `test_every_corpus_log_is_classified` and
   `test_every_known_fingerprint_has_a_corpus_entry` keep the two in step.
2. **`harness/corpus/benign/` pins the false-positive direction.** Widening a
   fingerprint to catch an unrelated startup failure would purge every model's
   compile cache on the node; these entries make that fail in CI instead.

## The corpus

`harness/corpus/manifest.yaml` pairs each captured failure log with the verdict
the worker must reach *and* the recovery it must perform. A fatal CUDA error
must not purge caches; a poisoned cache must purge and retry exactly once; a
rejected pre-sharded checkpoint must be discarded and retried unsharded; a
benign failure must do none of those. Adding an entry is adding a log file and a
manifest block — no test code.

## Layout

```
harness/
  gpusim/      state.py, scenario.py, server.py, bin/ (nvidia-smi, vllm, nvcc, cc), profiles/
  corpus/      captured vLLM failure logs + manifest.yaml
  lane.py      drives a real VllmProcessHandle against the simulator
  nodesim/     Dockerfile + entrypoint: the real worker, fake hardware
  stack/       docker-compose.e2e.yaml, seed.sql, compose.py
  clients/     admin client; SDK-based clients for the client tier
tests/gpu, tests/node, tests/client
../logos-ui/e2e/  Playwright config, auth setup, and browser specs
```

## What a node's state looks like

Worker liveness comes from `/internal/provider_status` — the orchestrator's
worker registry, the only place a live WebSocket session is visible. It is
deliberately *not* read from `scheduler_state`: that facade only lists a
provider once it has deployments attached, so a connected node with no models
yet reads as offline there. `AdminClient.connected_nodes()` combines the two
calls and unwraps the payload (`runtime.devices.devices` holds the per-card
list; `runtime.devices` itself is the summary with the telemetry flags).

## Adding a GPU profile

Drop a JSON file in `harness/gpusim/profiles/` with the card's real
`compute_cap` and `memory_total_mb`; `test_attention_backend_matches_compute_capability`
picks it up once it is listed in that test's `BACKEND_BY_PROFILE` map.
