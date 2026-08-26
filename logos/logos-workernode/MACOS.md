# Logos Worker Node on Apple Silicon (MLX / vllm-metal)

Runs Logos worker nodes on Apple Silicon Macs, serving MLX models through
[vllm-metal](https://github.com/vllm-project/vllm-metal) — a vLLM *platform
plugin* that keeps the `vllm serve` CLI and the OpenAI-compatible API while
swapping the compute backend for MLX.

The orchestrator sees an ordinary vLLM worker. It spawns, reconfigures and
deletes lanes exactly as it does on the CUDA nodes, and no protocol change was
needed to add one to the fleet.

---

## Why this node is not a container

**Metal cannot be passed into a container.** Docker Desktop on macOS runs a
Linux VM with no GPU passthrough, and Apple's own `container` framework has the
same limitation. MLX inside a container silently falls back to the CPU.

So the image built by CI is a **distribution artifact, never a runtime**:
`bootstrap-macos.sh` pulls it, copies the payload out with `docker cp`, and the
worker runs natively under launchd. Docker reached the same conclusion for
their own vllm-metal backend in Docker Desktop 4.62.

Running natively is also what preserves orchestrator control. A native process
can fork `vllm serve` subprocesses on command; a containerised worker could not
reach the host GPU to start them.

```
CI (GitHub Actions)                    Mac (native)
┌────────────────────────┐            ┌─────────────────────────────────┐
│ Dockerfile.mlx         │   pull     │ bootstrap-macos.sh              │
│  → source only,        │ ─────────► │  docker create + docker cp      │
│    no runtime          │            │   → ~/logos-workernode-mlx      │
│                        │            │  install-macos.sh               │
│ ghcr.io/ls1intum/      │            │   → ~/.venv-vllm-metal          │
│  edutelligence/        │            │  launchctl bootstrap            │
│  logos-workernode-mlx  │            │                                 │
└────────────────────────┘            │ logos_worker_node.main          │
                                      │  ├── outbound WS → orchestrator │
                                      │  └── subprocess: vllm serve     │
                                      │        → Metal GPU              │
                                      └─────────────────────────────────┘
```

---

## Requirements

| | |
|---|---|
| macOS | 15 (Sequoia) or later |
| CPU | Apple Silicon (arm64) — Rosetta Python cannot load MLX |
| Python | 3.12+, native arm64 |
| Docker | only to fetch and unpack the artifact |
| RAM | see the sizing table below |

---

## Install

```bash
curl -fsSLO https://raw.githubusercontent.com/ls1intum/edutelligence/main/logos/logos-workernode/scripts/bootstrap-macos.sh
chmod +x bootstrap-macos.sh
./bootstrap-macos.sh
```

This pulls the image, extracts it to `~/logos-workernode-mlx`, installs
vllm-metal into `~/.venv-vllm-metal`, and registers the launchd agent. It is
idempotent — re-run it to deploy a new version.

Then fill in credentials and start:

```bash
cd ~/logos-workernode-mlx
cat > .env <<'ENV'
LOGOS_URL=https://logos.example.tum.de
LOGOS_API_KEY=<worker key>
HF_TOKEN=<hf token>
LOGOS_SKIP_AUTO_CALIBRATION=1
ENV
$EDITOR config.yml          # seeded from config.example.mlx.yml
launchctl kickstart -k "gui/$(id -u)/de.tum.logos.workernode"
```

`LOGOS_SKIP_AUTO_CALIBRATION=1` is required — see *Calibration* below.

### Overrides

| Variable | Default | Purpose |
|---|---|---|
| `LOGOS_MLX_HOME` | `~/logos-workernode-mlx` | install root |
| `LOGOS_MLX_IMAGE` | `ghcr.io/…/logos-workernode-mlx:latest` | image to pull |
| `LOGOS_METAL_VENV` | `~/.venv-vllm-metal` | vllm-metal venv |
| `LOGOS_METAL_PYTHON` | resolved from the venv | interpreter for the MLX telemetry probe |
| `LOGOS_WORKER_BACKEND` | auto (`darwin` → metal) | force `metal` or `cuda` |

---

## Operating

```bash
tail -f ~/logos-workernode-mlx/logs/worker.log
launchctl print "gui/$(id -u)/de.tum.logos.workernode" | head -20
launchctl kickstart -k "gui/$(id -u)/de.tum.logos.workernode"   # restart
launchctl bootout "gui/$(id -u)/de.tum.logos.workernode"        # stop
```

### The account must stay logged in

The worker is a **LaunchAgent**, not a LaunchDaemon. Daemons run outside a login
session and do not reliably get GPU access, which would quietly demote every
lane to the CPU. On an unattended machine, enable auto-login (System Settings →
Users & Groups → Automatic login) and keep the session alive:

```bash
sudo pmset -a disablesleep 1
caffeinate -dimsu &
```

---

## Sizing

Unified memory: there is no separate VRAM pool. The budget is Metal's
`max_recommended_working_set_size` — roughly **78% of RAM** unless
`iogpu.wired_limit_mb` is set — not total RAM. The worker reports that number,
not `hw.memsize`, so the orchestrator does not schedule lanes that cannot become
resident.

```bash
sysctl hw.memsize iogpu.wired_limit_mb
~/.venv-vllm-metal/bin/python -c "import mlx.core as mx; print(mx.device_info())"
```

**Qwen3.8-27B** is unusually KV-hungry: 64 layers × 4 KV heads × head_dim 256 =
**256 KiB per token**, twice what a head_dim-128 model of the same size costs.
That is 8 GiB of KV cache for every 32k of context, and it dominates the sizing:

| RAM | GPU budget | 8bit (27.5 GB) | 4bit (15 GB) |
|---|---|---|---|
| 36 GB | ~28 GB | does not fit | ✅ up to ~16k context |
| 64 GB | ~50 GB | ✅ up to ~64k | ✅ comfortably |
| 128 GB | ~99 GB | ✅ up to ~256k | ✅ comfortably |

Raise the budget above the default fraction if needed (resets on reboot):

```bash
sudo sysctl iogpu.wired_limit_mb=57344   # e.g. 56 GB on a 64 GB Mac
```

`max_buffer_length` is a second, independent ceiling: Metal refuses any single
allocation above it however much memory is free. It is reported in the device
telemetry under `extra.max_buffer_length_mb`.

---

## What differs from a CUDA node

| | CUDA | Metal |
|---|---|---|
| Tensor parallelism | ✅ | ❌ one integrated GPU; a TP>1 lane is rejected at spawn |
| Sleep / wake | ✅ | ❌ needs CuMemAllocator → orchestrator uses stop/start |
| Auto-calibration | ✅ | ❌ hand-written profiles |
| CUDA graphs / torch.compile | ✅ | ❌ not applicable to MLX |
| Auto-placement across GPUs | ✅ | n/a — a single device |
| Model unload without stopping | ❌ | ❌ (identical: vLLM cannot unload weights) |
| Pre-spawn memory headroom gate | ✅ | ✅ |
| Lane spawn / delete / reconfigure | ✅ | ✅ |
| Model download (HF hub) | ✅ | ✅ |

Sleep is unavailable because vLLM's implementation is built on CUDA virtual
memory. `engines.vllm.disable_sleep_mode: true` makes lanes report
`sleep_state="unsupported"`, and the orchestrator reclaims memory by stopping
and restarting them instead. No capability is lost, only the mechanism differs.

### Calibration

`calibration.py` measures against `nvidia-smi` and samples `/proc/meminfo`,
neither of which exists on macOS. Run with `LOGOS_SKIP_AUTO_CALIBRATION=1` and
provide `model_profile_overrides` by hand; a profile with
`residency_source="override"` counts as valid, so the model is advertised
normally. `config.example.mlx.yml` has worked examples.

To measure `base_residency_mb`: start the lane, let it idle, then read
`used_memory_mb` from `GET /runtime`. Round up — underestimating makes the
planner over-subscribe the node.

---

## Troubleshooting

**Lane starts but inference is very slow.** The Metal plugin did not load and
everything is on the CPU. Check for `Platform plugin metal is activated` in the
lane log:

```bash
~/.venv-vllm-metal/bin/python -c "import vllm_metal, mlx.core as mx; print(mx.device_info())"
```

**Orchestrator never schedules anything.** It gates on reported free memory.
Confirm the node reports a budget:

```bash
curl -s localhost:8080/runtime | python3 -m json.tool | head -40
```

`devices.mode` must be `metal` and `total_memory_mb` non-zero. If
`degraded_reason` mentions *estimated*, the MLX probe failed and the figure is a
sysctl heuristic — set `LOGOS_METAL_PYTHON` to an interpreter that can import
mlx.

**Model advertised but never routed to.** It has no capacity profile; check the
startup log for `Excluding N uncalibrated model(s) from capabilities`.

**`[metal::malloc]` / `Insufficient Memory` in the lane log.** The model exceeds
the working set or `max_buffer_length`. Lower `max_model_len`, use a smaller
quantization, or raise `iogpu.wired_limit_mb`.

**`docker pull` denied.** The GHCR package is private until someone flips it to
public once (Package settings → Change visibility). Until then:
`echo $GITHUB_TOKEN | docker login ghcr.io -u <user> --password-stdin`

---

## Version pinning

Unlike the CUDA image, vLLM is **not** pinned here — `install.sh` upstream
installs a matched (vllm, mlx, torch) set, and pulling those apart is how you
get an unbootable lane. The two stacks therefore run different vLLM versions
(CUDA 0.28.x, vllm-metal 0.19.x at time of writing), which is why
`MetalVllmProcessHandle` builds its own command line rather than filtering the
CUDA one.

`logos_update-vllm.yml` only touches `Dockerfile`, not `Dockerfile.mlx`, so
automated vLLM bumps do not affect this path. `tests/test_metal_process.py`
cross-checks the generated flags against the installed vllm-metal whenever the
suite runs on a Mac, which is what catches an upstream flag rename.
