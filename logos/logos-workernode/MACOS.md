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
│  logos-workernode-mlx  │            │  launchctl bootstrap            │
│                        │            │                                 │
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
| vllm-metal | ≥ 0.3.0.dev20260826 for Qwen3.8 (0.2.0 cannot load it) |
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

The chat templates packaged with the image are merged into
`~/logos-workernode-mlx/chat-templates` (where the agent points
`LOGOS_CHAT_TEMPLATE_DIR`): templates the machine does not have yet are
copied in, files you added or edited yourself are never overwritten. A
template referenced in `config.yml` therefore works out of the box after the
first bootstrap — no hand-seeding.

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
| `LOGOS_MLX_IMAGE` | `ghcr.io/ls1intum/logos-workernode-mlx:latest` | image to pull |
| `LOGOS_METAL_VENV` | `~/.venv-vllm-metal` | vllm-metal venv — read by the installer *and* the runtime resolvers (vllm binary, telemetry interpreter); bootstrap passes it to the launchd agent. Upstream's installer always creates `~/.venv-vllm-metal`, so a custom path must be populated by you (e.g. upstream's editable install) |
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

**Qwen3.8-27B is a hybrid model**: 16 of its 64 layers use SDPA attention and
carry a growing KV cache; the other 48 are GDN linear layers with a fixed
per-sequence state. Only the SDPA layers scale with context, so the naive
"64 layers × 4 KV heads × head_dim 256" figure overstates the cost roughly
twofold.

Do not estimate — the plugin prints the real breakdown at lane startup:

```
Paged attention memory breakdown: metal_limit=30.15GB, fraction=0.92,
usable_metal=27.74GB, model_memory=15.13GB, overhead=1.16GB,
kv_budget=11.44GB, per_block_bytes=105902080, num_blocks=108,
max_tokens_cached=84672
Hybrid cache initialized: 16 SDPA layers (108 blocks), 48 linear layers
```

Measured on a 36 GB M3 Pro with the 4bit build (vllm-metal 0.3.0.dev20260826):
15.1 GB of weights, 11.4 GB of KV budget, 84672 tokens cached — about
135 KiB per token.

| RAM | usable Metal | 8bit (27.5 GB) | 4bit (15.1 GB) |
|---|---|---|---|
| 36 GB | ~27.7 GB | does not fit | ✅ measured, ~11 GB left for KV |
| 64 GB | ~46 GB | ✅ ~18 GB for KV | ✅ comfortably |
| 128 GB | ~91 GB | ✅ full context | ✅ comfortably |

Raise the budget above the default fraction if needed (resets on reboot):

```bash
sudo sysctl iogpu.wired_limit_mb=57344   # e.g. 56 GB on a 64 GB Mac
```

`max_buffer_length` is a second, independent ceiling: Metal refuses any single
allocation above it however much memory is free. It is reported in the device
telemetry under `extra.max_buffer_length_mb`.

One accounting quirk of unified memory: the reported GPU usage is the
*systemwide* wired-page count, and the host-RAM figure is the same machine's
`vm_stat` — so the same wired pages are visible to both gates, and a large
model looks tighter than it is on each of them. Both directions err toward
reporting less free memory, which is the safe side for a capacity planner,
but do not read the two numbers as independent pools.

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

## Privacy: whose prompts does this machine hold

A Metal lane is a **native process on the machine owner's hardware** — the
only possible deployment, since Metal cannot be containerised. That owner can
attach a debugger, read process memory, or capture the lane's logs. Prompts
routed to this node are therefore visible to the machine's operator, with no
attestation that the host is what it claims and no isolation between the
operator and the workload.

`LOCAL` in the router's privacy ordering means "our datacentre", not "not a
cloud" — so this machine must **not** be registered with the default
`LOCAL` privacy level, or callers who set `threshold_privacy = "LOCAL"` to
keep data on trusted infrastructure would silently be routed onto a personal
laptop. The privacy level for hardware outside operator control is
**`THIRD_PARTY_HARDWARE`**: when you add this Mac as a provider, select that
level. It orders below every cloud tier, so it is eligible only for requests
whose policy threshold explicitly allows third-party hardware — a Mac lane is
opt-in, and datacentre-only traffic never touches it.

The longer-term direction for exactly this shape of deployment is hardware
attestation (keys generated in the Secure Enclave, requests decryptable only
on the attested machine, debugger attachment blocked — the approach
[Darkbloom](https://www.darkbloom.dev/) uses for idle Apple Silicon). That
is a separate project; the distinct trust tier above closes the acute gap
without any cryptography.

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

The installer is pinned to a release tag **plus a SHA256 checksum** in
`install-macos.sh` (`VLLM_METAL_REF` / `VLLM_METAL_INSTALLER_SHA256`) — not
to `main`. This is an ordinary supply-chain concern for a CI image, but a
sharper one here: the installer executes on a contributor's personal Mac,
which is also the machine that will hold other people's prompts in memory. A
moving `main` can change the venv layout, the CLI flags the worker builds
against, or the wheel set it resolves — and the worker would only notice
when lanes stop starting. What runs must be exactly the bytes the checksum
describes.

vLLM itself is still **not** pinned directly: vllm-metal's `install.sh` pins
it by full wheel URL (PyPI carries no macOS vLLM wheel) together with a
matched mlx and torch; pulling that set apart is how you get an unbootable
lane. The pinned installer from the requirements table installs vLLM 0.28.0 —
the same release the CUDA image pins — and the installer's version floor
(`VLLM_METAL_MIN_VERSION`, asserted against the installed distribution on
every run) makes the documented requirement enforceable instead of
aspirational.

That is why `MetalVllmProcessHandle` builds its own command line instead of
filtering the CUDA one, and why `tests/test_metal_process.py` cross-checks the
generated flags against the *installed* vllm-metal whenever the suite runs on a
Mac. `logos_update-vllm.yml` only touches `Dockerfile`, not `Dockerfile.mlx`,
so automated vLLM bumps do not reach this path.

Keep vllm-metal current. It moves fast and dev builds are published daily;
Qwen3.8 support landed in 08/2026, and 0.2.0 could not serve it at all. To
upgrade, pick the release to move to, download its `install.sh`, then update
`VLLM_METAL_REF` **and** `VLLM_METAL_INSTALLER_SHA256` together in
`install-macos.sh` (bump `VLLM_METAL_MIN_VERSION` if the new floor applies)
and re-run it — it is idempotent. Do not pipe a fetched installer into bash:
verify the checksum first, as the installer now does for itself.

Two things to re-check after an upgrade, both of which changed between 0.2.0
and 0.3.0.dev: the `VLLM_METAL_*` names in `MetalConfig`
(`VLLM_METAL_BLOCK_SIZE` and `VLLM_METAL_PREFIX_CACHE*` were removed), and
whether any flag the worker emits has been renamed — the cross-check test
covers the second.
