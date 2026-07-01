# Benchmark Scenarios, Frameworks & Prerequisites

This benchmark compares **AnonTool** against two external dynamic serving frameworks
on the **same 4-GPU cluster** (2 nodes × 2 GPUs: `gpu-node-a`, `gpu-node-b`). All
scenarios serve the **same 5 models** and use the **same vLLM engine parameters**
so they are directly comparable.

## Scenarios

| Scenario        | What it is                                                                 | Role in the study |
|-----------------|----------------------------------------------------------------------------|-------------------|
| `anontool-sleep`   | AnonTool with the sleep/wake fast-path enabled (weights kept in CPU RAM, fast wake). | **Contribution** |
| `anontool-nosleep` | AnonTool with sleep/wake disabled → loads/evicts with a full reload, like the frameworks. | **Ablation** (isolates the sleep/wake benefit) |
| `ray`           | Ray Serve LLM, scale-to-zero per model.                                    | External framework baseline |
| `kserve`        | KServe on k3s, scale-to-zero per model via the Knative activator.          | External framework baseline |

Each scenario is run under every traffic pattern (`poisson`, `burst`, …; see
`--patterns`).

Why over-provisioning is required: 5 models, all `tensor_parallel_size=2` (2 GPUs
each), cannot all be resident on 4 GPUs at once — so every framework must load on
demand and evict idle models (scale-to-zero). `anontool-nosleep` and the two
frameworks all pay the **full cold-reload cost**; `anontool-sleep`’s wake fast-path
is what that cost is measured against.

## Strict no-interleaving

The AnonTool workernode (a **docker** stack) and the k3s pods (Ray/KServe) share the
**same physical GPUs**. They must never run at the same time. Before each scenario
sets up, the harness runs a **teardown barrier** (`_teardown_barrier`): it stops
every other serving stack and then polls `nvidia-smi` until all GPUs report their
memory freed (`_wait_for_gpus_idle_via_ssh`, < 2000 MiB) before the next scenario
loads. This makes runs reproducible regardless of leftovers from a previous run.

## vLLM version strings (report these)

| Component                  | Container image                                              | vLLM version |
|----------------------------|-------------------------------------------------------------|--------------|
| AnonTool workernode        | `icse27review/worker-vllm:latest`                           | **0.23.0**   |
| KServe model container     | `vllm/vllm-openai:v0.23.0`                                   | **0.23.0** (exact match to AnonTool) |
| Ray Serve LLM container    | `rayproject/ray-llm:2.56.0.637fd0-extra-py312-cu130`        | **0.22.0** (bundled; Ray 2.56.0) |

> The AnonTool stack is published as three public images — `icse27review/orchestrator`,
> `icse27review/db`, and `icse27review/worker-vllm` (all `:latest`) — and is what the
> benchmark drives for the `anontool-*` scenarios.
>
> Ray Serve LLM is locked to the vLLM bundled in its image (0.22.0). KServe runs
> an arbitrary container, so it uses the **exact** AnonTool vLLM (0.23.0). The
> 0.22.0↔0.23.0 difference for the Ray baseline is a reporting footnote only.

## Per-model vLLM run parameters

Identical across `anontool-*`, `ray`, and `kserve` (source: the workernode’s
calibrated `model_profiles.yml`). Defined in `benchmark_anontool.py` as
`_FRAMEWORK_MODEL_PARAMS`.

| Model                              | `tensor_parallel_size` | `max_model_len` |
|------------------------------------|------------------------|-----------------|
| `Qwen/Qwen3.6-35B-A3B`             | 2                      | 98208           |
| `google/gemma-3-12b-it`            | 2                      | 2704            |
| `google/gemma-3-4b-it`             | 2                      | 33888           |
| `meta-llama/Llama-3.1-8B-Instruct` | 2                      | 8192            |
| `microsoft/Phi-4-reasoning`        | 2                      | 5232            |

`enforce_eager=false` (matches calibration). `gpu_memory_utilization=0.90` is
applied uniformly to the framework baselines (`_FRAMEWORK_GPU_MEM_UTIL`); AnonTool
computes its own per load. All values are reported alongside results.

## Prerequisites

### Common (GPU nodes `gpu-node-a`, `gpu-node-b`)
- NVIDIA driver supporting CUDA 13.0 (Ray image is cu130); validated on driver 580.
- HuggingFace cache present at **`/mnt/ceph/.hf_cache`** on both nodes (models are
  read from here; gated models need a token).
- `HF_TOKEN` available in the workernode env file (`/opt/anontool-workernode/.env` or
  the configured `WORKERNODE_ENV`); the harness reads it from there for Ray/KServe.
- SSH reachable from the benchmark host (`anontool-test`) via the relay; `anontool-server`
  user with passwordless `sudo`.

### AnonTool scenarios
- AnonTool orchestrator + Traefik running (the harness does not tear these down).
- AnonTool workernode docker stack on each GPU node (`/opt/anontool-workernode`,
  `docker compose`). The harness starts/stops it and toggles sleep mode.
- A valid `--anontool-key`. Models calibrated (`model_profiles.yml`); run with
  `SKIP_CALIBRATION=1` to reuse the existing calibration.

### Ray Serve scenario
- Docker on each GPU node; image `rayproject/ray-llm:2.56.0.637fd0-extra-py312-cu130`
  pulled (the harness starts a Ray head on `gpu-node-a` + worker on `gpu-node-b`).
- **UFW:** allow `anontool-test → gpu-node-a:8000` (Ray Serve OpenAI endpoint).
- No k8s needed — standalone Ray in containers.

### KServe scenario (k3s)
A k3s cluster on the GPU nodes (server on `gpu-node-a`, agent on `gpu-node-b`) with:
- **NVIDIA k8s device plugin** + `RuntimeClass` named `nvidia` (GPU scheduling).
- **cert-manager**.
- **Istio** (ingress gateway).
- **Knative Serving** (operator 1.21.1; includes the **activator** for
  scale-from-zero) with feature flags (the harness ensures these, idempotently):
  - `kubernetes.podspec-runtimeclassname: enabled`
  - `kubernetes.podspec-volumes-hostpath: enabled`
  - `config-defaults: max-revision-timeout-seconds: "3600"`
- **KServe** controller (`kserve-resources` chart, **v0.19.0**) in **Serverless** mode.
- **UFW:** the harness opens `anontool-test → gpu-node-a:<NodePort>` (pinned to
  **31080**) for the benchmark host’s IP only.

The harness deploys one `InferenceService` per model (`minReplicas: 0`), pins the
Istio ingress to NodePort 31080, and routes per model by **Host header**
(`<isvc>.default.example.com`) — not the OpenAI `model` field. Pods are sized with
32–64 GiB memory + a 16 GiB `/dev/shm` (tp=2 NCCL); the default 2 GiB limit
OOM-kills vLLM during model load.

## Running

On the benchmark host (`anontool-test`), via `run_bench.sh` (env-driven):

```bash
# Short validation — 40 requests/run, all four scenarios, all patterns:
SCENARIOS="anontool-nosleep,anontool-sleep,ray,kserve" \
NUM_SAMPLES=40 SKIP_CALIBRATION=1 \
  /root/launch_branch.sh

# Full run — 1000 requests/run:
SCENARIOS="anontool-nosleep,anontool-sleep,ray,kserve" \
NUM_SAMPLES=1000 SKIP_CALIBRATION=1 \
  /root/launch_branch.sh
```

Key env knobs (see `run_bench.sh`): `SCENARIOS`, `PATTERNS`, `NUM_SAMPLES`,
`GSM8K_RPS`, `SEED`, `SKIP_PREPARE`, `SKIP_WARMUP`, `SKIP_CALIBRATION`, `SHELLY`
(wall-power capture). Results + charts are written under `benchmark_results/`.
