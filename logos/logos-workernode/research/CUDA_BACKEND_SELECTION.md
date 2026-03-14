# CUDA Backend Selection for Ollama in Docker

> **Critical finding**: Ollama running inside Docker containers can auto-select the wrong CUDA backend library, causing **10–15× slower model cold-starts** on certain GPU architectures. This document explains the problem, the fix, and provides benchmark evidence.

## The Problem

Ollama ships with two CUDA backend libraries:

- `cuda_v12/libggml-cuda.so` — compiled for CUDA 12.x
- `cuda_v13/libggml-cuda.so` — compiled for CUDA 13.x (CUDA toolkit 13, introduced with newer driver versions)

When Ollama starts, it auto-detects the highest compatible CUDA version and selects the corresponding backend. The selection logic depends on the CUDA runtime libraries available in the process environment.

### Host vs Docker: Different Selections

On the **same machine** with the same NVIDIA driver (e.g., 590.48.01, CUDA capability 13.1), Ollama makes **different backend choices** depending on whether it runs on the host or inside a Docker container:

| Environment | Backend Selected | Ollama Log Snippet |
|---|---|---|
| Host (systemd service) | `cuda_v12` | `libdirs=ollama,cuda_v12` |
| Docker container | `cuda_v13` | `libdirs=ollama,cuda_v13` |

This happens because the **NVIDIA Container Toolkit** (`nvidia-container-runtime`) injects its own CUDA runtime libraries into the container at startup. These injected libraries advertise CUDA 13.x capability, causing Ollama to prefer `cuda_v13` — even though the host Ollama correctly selects `cuda_v12`.

### Why It Matters: Graph Compilation Penalty

On GPUs with **compute capability 7.x** (e.g., Turing architecture: RTX 2000/3000/4000/5000 series, Quadro RTX), the `cuda_v13` backend triggers an extremely expensive ggml CUDA graph compilation phase during model loading. This phase takes **70–90 seconds** regardless of model size, turning what should be a fast cold-start into a painful delay.

The `cuda_v12` backend does not have this penalty on the same hardware — graph compilation completes in ~1–2 seconds.

## The Fix

Set the `OLLAMA_LLM_LIBRARY` environment variable to force the correct backend:

```bash
OLLAMA_LLM_LIBRARY=cuda_v12
```

### Docker Compose

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    environment:
      - OLLAMA_LLM_LIBRARY=cuda_v12
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

### Docker Run

```bash
docker run -d --gpus all -e OLLAMA_LLM_LIBRARY=cuda_v12 ollama/ollama:latest
```

### LogosWorkerNode (config.yml)

The logosworkernode supports this natively via the `llm_library` configuration field:

```yaml
ollama:
  llm_library: cuda_v12
```

This sets `OLLAMA_LLM_LIBRARY` in the managed Ollama container's environment.

## Benchmark Results

All benchmarks performed on the same machine with fresh container creation (no warm caches). Each test:

1. Forces a full container recreate (not just restart)
2. Waits for Ollama to become ready
3. Issues a single cold-start generation request (`num_predict: 1`)
4. Records `load_duration` from the Ollama API response (model load + GPU setup time)

### Hardware

| Component | Details |
|---|---|
| GPUs | 2× NVIDIA Quadro RTX 5000 (16 GiB each, 32 GiB total) |
| Compute Capability | 7.5 (Turing) |
| NVIDIA Driver | 590.48.01 |
| CUDA Capability | 13.1 |
| Ollama Version | 0.17.6 (Docker image `ollama/ollama:latest`) |

### Cold-Start Load Times

| Model | Size | cuda_v12 | cuda_v13 | Slowdown Factor |
|---|---|---|---|---|
| deepseek-r1:latest | 5.2 GB | **5.9s** | 91.3s | 15.5× |
| gemma3:4b | 3.3 GB | **7.5s** | 80.9s | 10.8× |
| gemma3:12b | 8.1 GB | **10.8s** | 85.4s | 7.9× |
| gemma3:27b | 17.4 GB | **17.7s** | 97.0s | 5.5× |

### Wall-Clock Times (Including Container Readiness)

| Model | cuda_v12 | cuda_v13 | Slowdown Factor |
|---|---|---|---|
| deepseek-r1:latest | **6.0s** | 106.7s | 17.8× |
| gemma3:4b | **7.7s** | 102.7s | 13.3× |
| gemma3:12b | **11.1s** | 107.2s | 9.7× |
| gemma3:27b | **18.0s** | 109.3s | 6.1× |

### Key Observations

1. **The `cuda_v13` penalty is roughly constant (~80–97s)** regardless of model size. This confirms it is a one-time graph compilation cost, not proportional to model weight loading.

2. **`cuda_v12` load time scales with model size** as expected: ~6s for 5 GB → ~18s for 17 GB. This is pure weight transfer to GPU memory.

3. **The relative slowdown is highest for small models** (15.5× for deepseek-r1 at 5.2 GB) because the fixed compilation overhead dominates. For large models, the weight loading time is a larger fraction of total time.

4. **This affects `num_parallel` reconfiguration**: Changing Ollama's `OLLAMA_NUM_PARALLEL` requires a process restart, which triggers a full model reload. Without the fix, every parallelism change costs ~85s instead of ~10s.

## Investigation Timeline

This section documents the diagnostic path for future reference.

### Symptom

Changing `num_parallel` from 4 to 8 via the logosworkernode took **~85 seconds**, with the model preload phase accounting for ~80s. The same model loaded in ~7s on the host Ollama service.

### Hypotheses Tested

| # | Hypothesis | Test | Result |
|---|---|---|---|
| 1 | Docker container restart overhead | Measured container create/start time | < 2s — not the cause |
| 2 | Ollama version regression (host 0.12.10 vs Docker 0.17.6) | Ran 0.12.10 in Docker | Still 77s — not the cause |
| 3 | Docker filesystem/network overhead | Bind-mounted host model files | No improvement |
| 4 | CUDA backend mismatch | Compared Ollama logs host vs Docker | **Root cause found** |

### Discovery

Comparing Ollama debug logs revealed the backend selection difference:

**Host** (fast, 7s):
```
msg="Dynamic LLM libraries" libdirs=ollama,cuda_v12
...
msg="model graph: fit=... alloc=..."   (gap: 1.6s)
```

**Docker** (slow, 80s):
```
msg="Dynamic LLM libraries" libdirs=ollama,cuda_v13
...
msg="model graph: fit=... alloc=..."   (gap: 71s)
```

The 71-second gap between `fit` and `alloc` log lines corresponds to ggml CUDA graph compilation — the kernel JIT compilation phase that is architecture-sensitive.

### Verification

```bash
# Slow (cuda_v13 auto-selected):
docker run --rm --gpus all ollama/ollama:latest
# → load_duration: ~85s

# Fast (cuda_v12 forced):
docker run --rm --gpus all -e OLLAMA_LLM_LIBRARY=cuda_v12 ollama/ollama:latest
# → load_duration: ~7s
```

## When to Apply This Fix

| Condition | Action |
|---|---|
| GPU compute capability ≤ 7.x (Turing and older) | **Set `OLLAMA_LLM_LIBRARY=cuda_v12`** |
| GPU compute capability ≥ 8.x (Ampere and newer) | Test both; newer GPUs may work fine with `cuda_v13` |
| Running Ollama on host (not Docker) | Usually auto-selects correctly; no fix needed |
| Running Ollama in Docker with NVIDIA Container Toolkit | **Always test and set explicitly** |

## Affected GPU Architectures

GPUs with compute capability 7.x (Turing) are confirmed affected:

- Quadro RTX 4000, 5000, 6000, 8000
- GeForce RTX 2060, 2070, 2080 (and Ti/Super variants)
- Tesla T4
- Titan RTX

Older architectures (Pascal 6.x, Volta 7.0) are likely also affected. Ampere (8.x) and newer architectures may handle `cuda_v13` without the compilation penalty, but this should be verified empirically.

## Related Configuration

The logosworkernode's `config.yml` supports these CUDA-related fields:

```yaml
ollama:
  # Force a specific CUDA backend library (recommended: cuda_v12 for Turing GPUs)
  llm_library: cuda_v12

  # GPU device allocation
  gpu_devices: all    # or "0", "0,1", etc.
```

The `llm_library` field is a restart-triggering field — changing it will recreate the Ollama container.
