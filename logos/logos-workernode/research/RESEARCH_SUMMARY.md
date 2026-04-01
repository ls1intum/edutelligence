# LogosWorkerNode — Research & Engineering Summary

> **Date**: March 2026
> **Hardware**: 2× Quadro RTX 5000 (16 GB each), Xeon Silver 4110 (16 cores), 187 GB RAM
> **Purpose**: This document captures all findings, benchmarks, architecture decisions, and known limitations from the multi-session research and implementation effort on the LogosWorkerNode project for the Logos/Edutelligence platform.

---

## Table of Contents

1. [Hardware Environment](#1-hardware-environment)
2. [Project Overview & Architecture](#2-project-overview--architecture)
3. [Implementation Phases](#3-implementation-phases)
4. [CUDA Backend Selection Discovery](#4-cuda-backend-selection-discovery)
5. [vLLM Backend Investigation](#5-vllm-backend-investigation)
6. [Ollama vs vLLM Benchmarks (TinyLlama 1.1B)](#6-ollama-vs-vllm-benchmarks-tinyllama-11b)
7. [GGUF-in-vLLM Investigation](#7-gguf-in-vllm-investigation)
8. [vLLM Tensor Parallelism + GGUF Bug](#8-vllm-tensor-parallelism--gguf-bug)
9. [FP16-Blocked Models in vLLM](#9-fp16-blocked-models-in-vllm)
10. [qwen3:30b-a3b Ollama Throughput Benchmark](#10-qwen330b-a3b-ollama-throughput-benchmark)
11. [Model Compatibility Matrix](#11-model-compatibility-matrix)
12. [Architecture Decisions & Rationale](#12-architecture-decisions--rationale)
13. [Known Limitations](#13-known-limitations)
14. [Recommendations & Next Steps](#14-recommendations--next-steps)
15. [Codebase Reference](#15-codebase-reference)
16. [March 2026 Follow-up: Lane Benchmark Validation](#16-march-2026-follow-up-lane-benchmark-validation)

---

## 1. Hardware Environment

```
Server:    hochbruegge.aet.cit.tum.de
CPU:       Intel Xeon Silver 4110 @ 2.10GHz (8 cores / 16 threads)
RAM:       187 GB DDR4
GPU 0:     Quadro RTX 5000  — 16,384 MiB VRAM, Bus 3B:00.0, NUMA 0
GPU 1:     Quadro RTX 5000  — 16,384 MiB VRAM, Bus AF:00.0, NUMA 1
GPU Arch:  Turing (SM 7.5, Compute Capability 7.5)
NVLink:    None (GPUs connected via PCIe, cross-NUMA SYS topology)
P2P:       Enabled (cuda can_device_access_peer: True in both directions)
NCCL:      Works via SHM/direct/direct transport
Driver:    NVIDIA 590.48.01
CUDA:      13.1 (driver capability)
CUDA TK:   12.8 installed at /usr/local/cuda-12.8/
Disk:      468 GB (md RAID) — ~8.6 GB free (critically low)
OS:        Ubuntu 22.04 / Linux 5.15
```

### GPU Limitations (Compute Capability 7.5 — Turing)

| Feature | Supported? | Minimum CC |
|---------|-----------|------------|
| FP32 | ✅ Yes | Any |
| FP16 (half precision) | ✅ Yes | 5.3 |
| BF16 (bfloat16) | ❌ No | 8.0 (Ampere) |
| FlashAttention v2 | ❌ No | 8.0 (Ampere) |
| FlashInfer (native) | ❌ No (Triton fallback works, ~10-20% slower) | 8.0 |
| Tensor Cores (FP16) | ✅ Yes | 7.0 |
| INT8 Tensor Cores | ✅ Yes | 7.5 |

**Key constraint**: No BF16 support. This is a hard blocker for several model architectures in vLLM (see Section 9).

---

## 2. Project Overview & Architecture

The **LogosWorkerNode** is a lightweight FastAPI daemon that manages GPU-accelerated LLM inference processes on a single GPU node for the Logos educational platform. It provides:

- **Multi-lane process pool**: Independent inference processes per model, each on its own port
- **Dual backend support**: Ollama (GGUF quantized, fixed-slot parallelism) and vLLM (continuous batching)
- **Hot-swap reconfiguration**: Atomic lane replacement with rollback on failure
- **VRAM budget management**: Per-lane GPU allocation with validation
- **Management API**: 23 REST endpoints for lifecycle, model, and lane management

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  GPU Node (hochbruegge)                                          │
│                                                                   │
│  ┌──────────────────┐          ┌────────────────────────────┐    │
│  │  LogosWorkerNode  │  manages │  Lane Pool                 │    │
│  │  FastAPI :8444    │─────────▶│                            │    │
│  │                   │          │  Lane 0: Ollama :11435     │    │
│  │  - Admin API      │          │    model=gemma3:27b        │    │
│  │  - GPU metrics    │          │    num_parallel=4          │    │
│  │  - Lane manager   │          │    GPU 0+1                 │    │
│  │  - VRAM budget    │          │                            │    │
│  │  - Event log      │          │  Lane 1: Ollama :11436     │    │
│  │                   │          │    model=qwen3:30b-a3b     │    │
│  └──────────────────┘          │    num_parallel=8          │    │
│         ▲                       │    GPU 0+1                 │    │
│         │ management            │                            │    │
│         │                       │  Lane N: vLLM :11437       │    │
│  ┌──────┴──────┐               │    model=deepseek-r1:8b    │    │
│  │   Logos     │               │    continuous batching      │    │
│  │   Server    │               │    GPU 0                    │    │
│  │             │──inference───▶│                            │    │
│  └─────────────┘  (direct)     └────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### Codebase Stats

| Metric | Value |
|--------|-------|
| Source files | 14 Python modules |
| Total lines | ~4,200 |
| Tests | 24 (all passing) |
| API endpoints | 23 (1 public + 22 authenticated) |
| Frameworks | FastAPI, Pydantic v2, httpx, PyYAML |

---

## 3. Implementation Phases

### Phase 1 — Core Multi-Process Infrastructure ✅

Built the lane manager (`LaneManager`) that spawns and manages multiple isolated Ollama processes. Each lane:
- Gets its own port (auto-assigned via `PortAllocator`)
- Runs one model with independent `num_parallel`, `context_length`, `kv_cache_type` settings
- Has full lifecycle: spawn → running → reconfigure → stop → destroy

The `ProcessHandle` Protocol abstracts the backend, enabling polymorphic lane management:

```python
@runtime_checkable
class ProcessHandle(Protocol):
    lane_id: str
    port: int
    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus: ...
    async def stop(self) -> ProcessStatus: ...
    async def reconfigure(self, lane_config: LaneConfig) -> ProcessStatus: ...
    # ... 13 methods total
```

### Phase 2 — VRAM Budget Management ✅

Implemented `VramBudgetManager` with:
- Per-lane VRAM estimation based on model size, context length, KV-cache type, and num_parallel
- Pre-flight validation: rejects lane configs that would exceed available VRAM
- KV-cache math: `per_slot_bytes = 2 × num_layers × (key_dim + value_dim) × context_length × dtype_size`
- Works for both Ollama (fixed slots) and vLLM (dynamic, uses `gpu_memory_utilization`)

### Phase 3 — Hot-Swap & Rollback ✅

Declarative `apply_lanes()` API:
1. Diff current lanes vs desired spec
2. Spawn new lanes on temporary ports
3. Validate health (wait for /api/tags or /v1/models)
4. Atomically swap handles (port reassignment)
5. On any failure → rollback to previous state

All transitions logged in the event system (`EventLog`) for observability.

### Phase 4 — vLLM Backend Integration ✅

`VllmProcessHandle` manages a vLLM subprocess:
- Builds command: `vllm serve <model> --host --port --dtype --max-model-len ...`
- `_build_env()`: Auto-detects CUDA_HOME from common paths (`/usr/local/cuda`, `/usr/local/cuda-12.8`, `/usr/local/cuda-12`)
- Supports: `enable_prefix_caching`, `enforce_eager`, `tensor_parallel_size`, `gpu_memory_utilization`, `quantization`, `extra_args`
- Translates Ollama-style model operations to vLLM equivalents (some no-ops since vLLM auto-manages models)

Config example:
```yaml
lanes:
  - model: meta-llama/Llama-3.2-3B-Instruct
    backend: vllm
    context_length: 8192
    gpu_devices: "0"
    vllm:
      tensor_parallel_size: 1
      gpu_memory_utilization: 0.90
      dtype: auto
      enforce_eager: false
      enable_prefix_caching: true
      extra_args: []
```

---

## 4. CUDA Backend Selection Discovery

### Problem

Ollama in Docker auto-selects `cuda_v13` backend library, causing **10–15× slower model cold-starts** on Turing GPUs. The NVIDIA Container Toolkit injects CUDA 13.x runtime libraries, making Ollama believe cuda_v13 is preferred.

### Root Cause

On compute capability 7.5, `cuda_v13/libggml-cuda.so` triggers a ~75-second ggml CUDA graph compilation penalty during model loading. The `cuda_v12` backend does not have this penalty.

| Environment | Backend Selected | Cold Start |
|---|---|---|
| Host (systemd) | cuda_v12 | ~7 seconds |
| Docker (default) | cuda_v13 | **~80 seconds** |
| Docker (with fix) | cuda_v12 | ~7.9 seconds |

### Fix

```bash
OLLAMA_LLM_LIBRARY=cuda_v12
```

Implemented in `OllamaConfig.llm_library` field, wired into `_build_env()`. Also tracked in `_RESTART_FIELDS` so changing it triggers a process restart.

### Benchmark Evidence

| Scenario | Before Fix | After Fix | Speedup |
|---|---|---|---|
| Cold model load | 80s | 7.9s | **10.1×** |
| 4→8 num_parallel reconfigure | 85s | 10s | **8.5×** |

---

## 5. vLLM Backend Investigation

### Motivation

Ollama uses fixed `num_parallel` KV-cache slots — once all slots are busy, additional requests queue. This creates a hard concurrency ceiling. vLLM uses **continuous batching** (PagedAttention) which dynamically allocates KV-cache pages per request, theoretically handling unlimited concurrent requests up to VRAM limits.

### Setup

- **vLLM Version**: 0.17.0
- **PyTorch**: 2.10.0+cu128
- **Installation**: `pip install vllm==0.17.0` into `.venv/`
- **CUDA Toolkit**: 12.8 at `/usr/local/cuda-12.8/` (required for FlashInfer JIT compilation)

### Key Findings During Setup

1. **FlashInfer**: Unavailable natively (needs CC 8.0+), falls back to Triton backend (~10-20% slower but functional)
2. **FlashAttention v2**: Not supported on CC 7.5 (Turing) — vLLM uses xformers or eager attention instead
3. **`--enforce-eager`**: Required to avoid CUDA graph compilation issues on Turing
4. **`vllm serve` CLI**: Replaced the old `python -m vllm.entrypoints.openai.api_server` in v0.17.0
5. **`--disable-log-requests`**: Removed in v0.17.0 — caused startup errors if included
6. **Cold start**: 63 seconds for TinyLlama 1.1B (vs ~2-3 seconds for Ollama)

---

## 6. Ollama vs vLLM Benchmarks (TinyLlama 1.1B)

Benchmark conducted with TinyLlama 1.1B (small enough to fit on a single GPU in both backends), 128-token generation, varying concurrency.

### Results

| Concurrency | vLLM tok/s | Ollama tok/s | Winner | Margin |
|-------------|-----------|-------------|--------|--------|
| N=1 | ~800 | ~1600 | **Ollama** | 2.0× |
| N=4 | ~400 | ~600 | **Ollama** | 1.5× |
| N=8 | ~463 | ~418 | **vLLM** | 1.1× |
| N=16 | ~941 | ~455 | **vLLM** | 2.1× |
| N=32 | ~1513 | ~451 | **vLLM** | 3.4× |

### Time to First Token (TTFT)

| Concurrency | vLLM | Ollama | Winner |
|-------------|------|--------|--------|
| N=1 | 85ms | 175ms | **vLLM** 2× |
| N=8 | ~200ms | ~2s | **vLLM** 10× |

### Key Takeaway

**vLLM's continuous batching scales linearly** — at N=32, it produces 3.4× more tokens/s than Ollama. Ollama saturates at its `num_parallel` ceiling (4 slots in this test) and throughput plateaus while latency climbs linearly.

**Ollama wins at low concurrency** (N=1-4) due to lower overhead and faster model loading.

---

## 7. GGUF-in-vLLM Investigation

### Motivation

vLLM typically uses HuggingFace safetensors format, requiring separate (larger) model downloads. If vLLM can load Ollama's existing GGUF files directly, we get:
- Zero additional downloads (reuse Ollama's model cache)
- Same quantization level (Q4_K_M → ~4.5 bits/param)
- Reduced VRAM usage compared to FP16 safetensors

### Approach

vLLM 0.17.0 supports `--quantization gguf` natively. Ollama stores GGUF blobs at:
```
/usr/share/ollama/.ollama/models/blobs/sha256-<hash>
```

We created zero-copy symlinks from these blobs to user-accessible paths:
```bash
ln -s /usr/share/ollama/.ollama/models/blobs/sha256-<hash> /tmp/model.gguf
```

### gemma3:27b GGUF Attempt — BLOCKED

```bash
vllm serve /tmp/gemma3-27b-q4_k_m.gguf --quantization gguf --dtype float16
```

**Result**: GGUF loaded successfully (weights parsed in ~126 seconds), but then:
```
ValueError: The model type 'gemma3_text' does not support float16.
Reason: Numerical instability.
Please use bfloat16 or float32 instead.
```

**Root cause**: vLLM's `_FLOAT16_NOT_SUPPORTED_MODELS` in `config/model.py` hardcodes gemma3 as FP16-incompatible. Since our RTX 5000s don't support BF16 (needs Ampere CC 8.0+), and FP32 would need ~70 GB VRAM, **gemma3 cannot run on vLLM with this hardware**.

### qwen3:30b-a3b GGUF Attempt — TP BUG

The GGUF file is 18.56 GB — too large for a single 16 GB GPU. Tensor parallelism (TP=2) was attempted to split across both GPUs. See Section 8.

---

## 8. vLLM Tensor Parallelism + GGUF Bug

### Problem

Attempting to serve an 18 GB GGUF file with TP=2 across two GPUs:
```bash
vllm serve /tmp/qwen3-30b-a3b.gguf \
  --quantization gguf --tensor-parallel-size 2 \
  --dtype float16 --gpu-memory-utilization 0.90
```

**Fails every time** with:
```
ValueError: Free memory on device cuda:0 (1.38/15.55 GiB) on startup is less
than desired GPU memory utilization (0.9, 14.0 GiB).
```

### Root Cause (Diagnosed)

The crash is **NOT** a GPU hardware issue. NCCL initializes perfectly:
```
NCCL INFO ncclCommInitRank comm ... rank 0 nranks 2 - Init COMPLETE
NCCL INFO Channel 00 : 0[0] -> 1[1] via SHM/direct/direct
```

The issue is in **vLLM's GGUF loading pathway** (`gguf_loader.py`). During model initialization:

```python
target_device = torch.device(device_config.device)   # always cuda:0
with target_device:
    model = initialize_model(...)   # allocates full model on GPU 0
self.load_weights(model, ...)       # loads all 18 GB onto GPU 0 first
```

The GGUF loader was **designed for single-GPU operation**. With TP=2:
1. The parent/APIServer process pre-loads ~14 GB of GGUF data onto GPU 0 during config parsing
2. Worker 0 (GPU 0) starts and finds only 1.38 GiB free → **fails memory check**
3. Worker 1 (GPU 1) has 15.29 GiB free (fine, but worker 0 already crashed)
4. NCCL channel breaks → rank 1 gets "Broken pipe"

This was verified by:
- Testing at `--gpu-memory-utilization 0.50` → same 1.38 GiB free on GPU 0
- Checking the debug logs: Worker 0 always OOMs regardless of utilization setting
- Confirming GPU 1 is always healthy

### Verdict

**This is a vLLM 0.17.0 bug** — GGUF + TP is fundamentally broken when the GGUF file exceeds a single GPU's VRAM. The safetensors loader handles TP correctly (shard-aware from the start), but the GGUF path loads everything onto device 0 first.

| Scenario | Result |
|----------|--------|
| GGUF + TP=1, model ≤ 16 GB | ✅ Works |
| GGUF + TP=2, model > 16 GB | ❌ Bug — OOM on GPU 0 |
| Safetensors + TP=2 | ✅ Works (but needs FP16 weights → huge download) |

---

## 9. FP16-Blocked Models in vLLM

vLLM maintains a hardcoded list in `vllm/config/model.py` (`_FLOAT16_NOT_SUPPORTED_MODELS`) of architectures that cannot use FP16 due to numerical instability:

| Blocked Architecture | Reason |
|---------------------|--------|
| `gemma2` | Numerical instability in FP16 |
| `gemma3` | Numerical instability in FP16 |
| `gemma3_text` | Numerical instability in FP16 |
| `plamo2` | Numerical instability in FP16 |
| `glm4` | Numerical instability in FP16 |

**Impact on our hardware**: Since RTX 5000 (CC 7.5) only supports FP16 (no BF16), all Gemma family models are **permanently blocked from vLLM on this hardware**. FP32 fallback is not viable (2× VRAM, exceeds capacity for any model > 8B).

---

## 10. qwen3:30b-a3b Ollama Throughput Benchmark

Benchmarked qwen3:30b-a3b on Ollama (the only viable backend for this model on our hardware) with `OLLAMA_NUM_PARALLEL=4`.

### Test Parameters

- **Prompt**: Realistic code-review task (~150 input tokens)
- **Max output**: 200 tokens
- **Concurrency levels**: 1, 4, 8, 16, 32
- **Model**: qwen3:30b-a3b (MoE, 30B total / ~3B active per token)
- **Quantization**: Q4_K_M (18. GB GGUF)
- **Note**: qwen3 thinking mode was active (could not be disabled via OpenAI API); counts include reasoning tokens

### Results

| N | Aggregate tok/s | Avg Latency | P50 Latency | P95 Latency | Avg TTFT | Errors |
|---|----------------|-------------|-------------|-------------|----------|--------|
| 1 | 15.8 | 12.70s | 12.70s | 12.70s | 295ms | 0 |
| 4 | 29.9 | 26.60s | 26.62s | 26.62s | 1,481ms | 0 |
| 8 | 34.8 | 34.59s | 34.56s | 45.95s | 11,985ms | 0 |
| 16 | 35.4 | 56.91s | 57.28s | 90.29s | 34,636ms | 0 |
| 32 | 35.3 | 101.61s | 101.46s | 180.87s | 79,255ms | 0 |

### Analysis

- **Ollama saturates at ~35 tok/s** regardless of concurrency beyond N=8
- **TTFT degrades severely**: 295ms at N=1 → 79 seconds at N=32 (270× worse)
- **Latency scales linearly** with concurrency beyond `num_parallel=4`
- qwen3's thinking mode generated significant reasoning tokens, consuming most of the 200-token budget on reasoning rather than answer content

### qwen3 Thinking Mode Issue

The OpenAI-compatible `/v1/chat/completions` endpoint puts tokens in a `reasoning` field (not `content`) during the thinking phase:
```json
{"delta": {"content": "", "reasoning": "Okay, the user..."}}
```

Neither `/nothink` prefix in content nor Ollama's `"think": false` parameter successfully disabled thinking mode during our tests. This is a significant limitation for throughput benchmarks and production use — the model wastes tokens on chain-of-thought that isn't needed for simple tasks.

---

## 11. Model Compatibility Matrix

### Available Models on This Node

| Model | Architecture | GGUF Size | vLLM FP16? | vLLM GGUF+TP? | Ollama? | Notes |
|-------|-------------|-----------|-----------|---------------|---------|-------|
| gemma3:4b | gemma3 | ~3 GB | ❌ FP16-blocked | N/A | ✅ Works | |
| gemma3:12b | gemma3 | ~8 GB | ❌ FP16-blocked | N/A | ✅ Works | |
| gemma3:27b | gemma3 | 17.4 GB | ❌ FP16-blocked | N/A | ✅ Works | Primary workhorse |
| qwen3:30b-a3b | qwen3_moe | 18.6 GB | ✅ Not blocked | ❌ Bug (>16 GB) | ✅ Works | MoE, thinking mode |
| deepseek-r1:8b | qwen2 | ~5 GB | ✅ Not blocked | ✅ Fits 1 GPU | ✅ Works | Best vLLM candidate |
| deepseek-r1:70b | deepseek | ~40 GB | ✅ Not blocked | ❌ Too large | ❌ Too large | Needs >32 GB |
| qwen2.5-coder:32b | qwen2 | ~20 GB | ✅ Not blocked | ❌ Bug (>16 GB) | ✅ Works | |
| magistral:24b | mistral | ~15 GB | ✅ Not blocked | ✅ Fits 1 GPU | ✅ Works | Good vLLM candidate |
| llama3.3:latest | llama | ~40 GB | ✅ Not blocked | ❌ Too large | ❌ Too large | Needs >32 GB |

### Decision Matrix

```
Is the model in FP16-blocked list (gemma2/3, plamo2, glm4)?
  ├── YES → Ollama only (on CC 7.5 hardware)
  └── NO → Does the GGUF fit in 1 GPU (≤14 GB)?
              ├── YES → vLLM viable (single GPU, GGUF quantization)
              └── NO  → Is safetensors FP16 ≤ 32 GB total?
                          ├── YES → vLLM with TP=2 (safetensors, not GGUF)
                          └── NO  → Ollama only (handles multi-GPU GGUF natively)
```

---

## 12. Architecture Decisions & Rationale

### Why Dual Backend?

| Decision | Rationale |
|----------|-----------|
| Ollama for large quantized models | Ollama handles GGUF natively, supports multi-GPU without TP bugs, fast cold starts (~3s), mature GGUF runtime |
| vLLM for high-concurrency lanes | Continuous batching scales linearly (3.4× at N=32 vs Ollama), prefix caching saves TTFT for repeated system prompts |
| ProcessHandle Protocol | Single interface for both backends enables hot-swap without backend-specific logic in LaneManager |
| Lane-per-model isolation | Each model gets dedicated VRAM allocation, avoids Ollama's model swapping overhead |

### Why Not Just vLLM for Everything?

1. **gemma3 (our primary model) is FP16-blocked** — literally cannot run on vLLM with CC 7.5
2. **GGUF + TP is broken in vLLM 0.17.0** — models > 16 GB can't use tensor parallelism
3. **63-second cold start** vs Ollama's 3 seconds
4. **Ollama wins at low concurrency** (N=1-4) which is common for development/testing

### Why Multi-Lane Instead of Single Process?

| Feature | Single Ollama | Multi-Lane |
|---------|--------------|------------|
| Model isolation | ❌ Models share VRAM, swap in/out | ✅ Each model has dedicated VRAM |
| Per-model tuning | ❌ One `num_parallel` for all | ✅ Different settings per model |
| Mixed backends | ❌ Ollama only | ✅ Ollama + vLLM per lane |
| Hot-swap | ❌ Full restart | ✅ Atomic per-lane replacement |
| VRAM efficiency | ❌ Loaded models compete for VRAM | ✅ Budget manager prevents overcommit |

---

## 13. Known Limitations

### Hardware Limitations (CC 7.5 / Turing)

1. **No BF16**: Blocks gemma family from vLLM entirely
2. **No FlashAttention v2**: Reduces vLLM decode throughput by ~15-30%
3. **FlashInfer via Triton fallback**: Additional ~10-20% overhead
4. **16 GB per GPU**: Limits single-GPU models to ≤14 GB GGUF
5. **PCIe (no NVLink)**: Cross-GPU communication ~10× slower than NVLink
6. **Cross-NUMA GPUs**: GPU 0 on NUMA 0, GPU 1 on NUMA 1 — suboptimal for TP

### Software Limitations

1. **vLLM GGUF + TP bug**: Models > 1 GPU VRAM cannot use tensor parallelism with GGUF format
2. **vLLM FP16 block list**: gemma2, gemma3, gemma3_text, plamo2, glm4 hardcoded as incompatible
3. **qwen3 thinking mode**: Cannot be reliably disabled via OpenAI API in Ollama — wastes tokens on reasoning
4. **Disk space**: Only ~8.6 GB free on 468 GB RAID — cannot store additional large model weights
5. **Ollama concurrency ceiling**: `num_parallel` is a hard limit; beyond it, requests queue with linear latency increase

### Operational Limitations

1. **Cold start asymmetry**: vLLM takes 60+ seconds vs Ollama's 3 seconds
2. **GGUF-only ecosystem**: Most models on this node are GGUF-quantized for Ollama — safetensors versions would need 2-4× the disk space
3. **No model format conversion**: Cannot convert GGUF → safetensors without the full FP16 weights

---

## 14. Recommendations & Next Steps

### Immediate (Current Hardware)

1. **gemma3:27b → Ollama only.** No workaround for FP16 block + GGUF TP bug. Tune `OLLAMA_NUM_PARALLEL` (4-8) for best concurrency vs latency tradeoff.

2. **deepseek-r1:8b → Best vLLM candidate.** 5 GB GGUF fits on single GPU. Test continuous batching + prefix caching benefit.

3. **magistral:24b → Viable for vLLM** if GGUF ≤ 14 GB after overhead. Verify actual GGUF size.

4. **Hybrid lane strategy:** Run gemma3 lanes on Ollama, smaller models on vLLM. The LaneManager already supports mixed backends.

### Future (Hardware Upgrade Path)

| Hardware | Unlocks |
|----------|---------|
| Ampere GPUs (A100/A6000, CC 8.0+) | BF16 → gemma3 on vLLM, FlashAttention v2, FlashInfer native |
| NVLink bridge | 10× faster TP communication, viable for TP=2 with large models |
| 24+ GB GPUs | Larger GGUF files fit on single GPU, bypasses TP bug |
| More disk | Room for safetensors format models (enables vLLM TP with non-GGUF) |

### Software Fixes to Watch

1. **vLLM GGUF + TP fix**: Track vLLM GitHub issues — once the GGUF loader is made shard-aware, TP=2 with 18 GB GGUF would work
2. **vLLM FP16 gemma3 override**: If a future version allows forced FP16 (with quality degradation warning), gemma3 could run on vLLM
3. **Ollama continuous batching**: If Ollama ever adopts PagedAttention/continuous batching, the vLLM advantage disappears

---

## 15. Codebase Reference

### File Structure

```
logos-workernode/
├── .env.example                  # Environment variable template (all config)
├── AGENTS.md                     # AI agent project guide
├── CUDA_BACKEND_SELECTION.md     # CUDA v12 vs v13 findings
├── RESEARCH_SUMMARY.md           # This file
├── bench_qwen3.py                # qwen3 throughput benchmark (Ollama vs vLLM)
├── bench_reconfigure.py          # Reconfiguration latency benchmark
├── test_lanes.py                 # Multi-lane parallelism test
├── test_concurrency.py           # Lane A/B timing comparison
├── logos_worker_node/
│   ├── main.py          (196 L)  # FastAPI app, lifespan, uvicorn entry
│   ├── admin_api.py     (541 L)  # Management endpoints (23 routes)
│   ├── logos_api.py     (131 L)  # Logos status endpoints
│   ├── auth.py          (55 L)   # Bearer token authentication
│   ├── config.py        (164 L)  # Env-var config loading and state persistence
│   ├── models.py        (412 L)  # Pydantic models (OllamaConfig, VllmConfig, LaneConfig, etc.)
│   ├── lane_manager.py  (597 L)  # Multi-lane orchestration, hot-swap, event log
│   ├── process_handle.py (45 L)  # ProcessHandle Protocol (backend interface)
│   ├── ollama_process.py (395 L) # Ollama lane process handle
│   ├── vllm_process.py  (341 L)  # vLLM lane process handle
│   ├── vram_budget.py   (95 L)   # VRAM estimation & validation
│   ├── ollama_manager.py (419 L) # Single Ollama process management
│   ├── ollama_status.py (191 L)  # Ollama status polling
│   └── gpu.py           (161 L)  # nvidia-smi GPU metrics collector
└── tests/
    └── test_logos_worker_node.py (474 L) # 24 unit tests
```

### Key Configuration (environment variables)

```yaml
controller:
  port: 8444
  api_key: RANDOM_DEFAULT_KEY
  gpu_poll_interval: 5
  ollama_poll_interval: 5
ollama:
  ollama_binary: /usr/local/bin/ollama
  port: 11435
  gpu_devices: all
  num_parallel: 4
  context_length: 1024
  flash_attention: true
  kv_cache_type: q8_0
  llm_library: cuda_v12       # Critical: forces CUDA 12 backend (10× faster cold start)
  models_path: /usr/share/ollama/.ollama/models
lanes: []                     # Multi-lane configs go here
```

### VllmConfig Model

```python
class VllmConfig(BaseModel):
    vllm_binary: str = "vllm"
    tensor_parallel_size: int = 1
    max_model_len: int | None = None
    dtype: str = "auto"
    quantization: str | None = None
    gpu_memory_utilization: float = 0.90
    enforce_eager: bool = False
    enable_prefix_caching: bool = True
    extra_args: list[str] = []
```

---

## 16. March 2026 Follow-up: Lane Benchmark Validation

This section captures the latest validation runs done after the initial research sections above. It reflects the exact behavior observed on March 10, 2026 with the current lane orchestration and benchmark scripts.

### 16.1 DeepSeek-R1-0528-Qwen3-8B on vLLM (TP=2, FP16)

Run profile:
- Model: `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`
- Backend: vLLM lane
- GPUs: `0,1`, `tensor_parallel_size=2`
- `dtype=float16`, `enforce_eager=true`
- `gpu_memory_utilization=0.70`
- Concurrency: `32,64`
- Prompt modes: `varied_unique_prefix` and `fixed_shared_prefix`

Measured results:

| Prompt Mode | Prefix Cache | N | Aggregate tok/s | TTFT (ms) | P95 Latency (s) | Peak Total GPU Memory |
|---|---|---:|---:|---:|---:|---:|
| varied_unique_prefix | off | 32 | 788.674 | 900.9 | 8.103 | 23.5 GiB |
| varied_unique_prefix | on | 32 | 815.964 | 886.3 | 7.835 | 23.5 GiB |
| varied_unique_prefix | off | 64 | 1259.384 | 1509.3 | 10.138 | 23.5 GiB |
| varied_unique_prefix | on | 64 | 1259.290 | 1476.1 | 10.119 | 23.5 GiB |
| fixed_shared_prefix | off | 32 | 882.947 | 306.5 | 7.242 | 23.5 GiB |
| fixed_shared_prefix | on | 32 | 794.145 | 311.2 | 8.053 | 23.5 GiB |
| fixed_shared_prefix | off | 64 | 1563.291 | 460.5 | 8.182 | 23.5 GiB |
| fixed_shared_prefix | on | 64 | 1507.732 | 431.7 | 8.483 | 23.5 GiB |

Primary conclusion:
- This model/profile runs stably at about **23.5 GiB total GPU residency** on this node (roughly 12 GiB per GPU), materially below earlier conservative estimates based on `gpu_memory_utilization=0.9`.

### 16.2 Operational Footguns Found During Validation

1. `bench_lane_backends.py` defaulted to `--vllm-quantization awq`.
   - This breaks full-precision checkpoints with:
   - `Value error, Cannot find the config file for awq`.
   - Resolution: script now normalizes quantization with `auto|none|explicit` modes and infers AWQ only when model name contains `AWQ`.

2. vLLM startup could fail when HF cache path was under an unwritable Ollama models directory.
   - Example: `/usr/share/ollama/.ollama/models/.hf_cache` permission errors on host user runs.
   - Resolution: vLLM lane env now falls back to `~/.cache/huggingface` if preferred cache path is not writable.

3. Port allocation should account for host-occupied ports, not only reserved/internal ones.
   - Resolution: `PortAllocator` now skips ports already bound on host, reducing lane apply failures in mixed local/service environments.

### 16.3 Practical Memory Sizing Guidance (Validated)

For TP=2 and vLLM:
- `gpu_memory_utilization` is the per-GPU cap for this vLLM instance.
- Model + runtime overhead is mostly fixed after load.
- KV cache occupies the remaining budget and grows with active tokens.

Useful workflow:
1. Start with conservative `gpu_memory_utilization` (for example `0.70`).
2. Verify throughput/error behavior at target concurrency.
3. Lower budget in small steps (`0.65`, `0.60`, `0.58`, ...) until first instability.
4. Keep a safety margin above that floor for production.

---

## Appendix: Ollama System Configuration

```ini
# /etc/systemd/system/ollama.service (relevant excerpts)
OLLAMA_NUM_PARALLEL=4
```

## Appendix: Key Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `OLLAMA_LLM_LIBRARY` | `cuda_v12` | Force CUDA 12 backend (avoid 75s graph compilation) |
| `CUDA_HOME` | `/usr/local/cuda-12.8` | For FlashInfer JIT compilation in vLLM |
| `OLLAMA_NUM_PARALLEL` | `4` | Default concurrent request slots per Ollama process |

## Appendix: Symlink Approach for GGUF-in-vLLM

To serve Ollama's existing GGUF files via vLLM without copying:
```bash
# 1. Find the blob hash from Ollama's manifest
python3 -c "
import json
with open('/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library/<model>/<tag>') as f:
    m = json.load(f)
for layer in m['layers']:
    if 'model' in layer['mediaType']:
        print(layer['digest'].replace(':', '-'))
"

# 2. Make Ollama's blob directory traversable
sudo chmod o+x /usr/share/ollama /usr/share/ollama/.ollama \
  /usr/share/ollama/.ollama/models /usr/share/ollama/.ollama/models/blobs

# 3. Create zero-copy symlink
ln -s /usr/share/ollama/.ollama/models/blobs/sha256-<hash> /tmp/model.gguf

# 4. Serve via vLLM
vllm serve /tmp/model.gguf --quantization gguf --dtype float16 --enforce-eager
```
