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
`bootstrap-macos.sh` pulls it straight from the registry over HTTPS, untars
the payload out of its layers, and the worker runs natively under launchd. No
container runtime is involved on the Mac at all. Docker reached the same
conclusion for their own vllm-metal backend in Docker Desktop 4.62.

Running natively is also what preserves orchestrator control. A native process
can fork `vllm serve` subprocesses on command; a containerised worker could not
reach the host GPU to start them.

```
CI (GitHub Actions)                    Mac (native)
┌────────────────────────┐            ┌─────────────────────────────────┐
│ Dockerfile.mlx         │   HTTPS    │ bootstrap-macos.sh              │
│  → source only,        │ ─────────► │  registry pull + untar payload/ │
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
| Python | 3.12 or newer — **installed by the bootstrap** |
| Homebrew, git, uv | **installed by the bootstrap** |
| Docker | not needed |
| vllm-metal | ≥ 0.29.0 — Qwen3.8 needs ≥ 0.28.0, embedders need 0.29.0 |
| RAM | see the sizing table below |

macOS ships Python 3.9, which cannot run this worker (pydantic v2 evaluates
`bool | None` annotations at import, which needs 3.10+). The bootstrap installs
a supported interpreter itself and the installer refuses anything older, rather
than building a venv that fails later with an unrelated-looking import error.

---

## Install

On a freshly installed Mac this is the only step:

```bash
curl -fsSLO https://raw.githubusercontent.com/ls1intum/edutelligence/main/logos/logos-workernode/scripts/bootstrap-macos.sh
chmod +x bootstrap-macos.sh
./bootstrap-macos.sh
```

It installs its own prerequisites (Homebrew, git, uv, `python@3.13` — each
skipped when already present), fetches the distribution image, extracts it to
`~/logos-workernode-mlx`, installs vllm-metal into `~/.venv-vllm-metal`,
registers the launchd agent, and disables sleep so the machine keeps serving
with the lid closed. Expect two password prompts: Homebrew and `pmset` both
need `sudo`.

It is idempotent — **re-running it is also the upgrade path**. Operator state
(`config.yml`, `.env`, `data/`, `logs/`, `cache/`) is preserved; only code and
runtime are replaced.

| Flag | Effect |
|---|---|
| `--no-deps` | Skip the Homebrew/git/uv/python step, for machines whose toolchain is managed by Ansible or MDM |
| `--no-power-settings` | Leave sleep behaviour alone |
| `<image-ref>` | Install a specific tag instead of `:latest`, e.g. a PR build |

**No container runtime is involved.** The image is never started — Metal does
not exist inside containers — so the bootstrap pulls it straight from the
registry over HTTPS with an anonymous token and untars the `payload/` directory
out of its layers. That keeps Docker Desktop, a GUI application with a licence
dialog on first launch, off a machine meant to run headless.

The chat templates packaged with the image are merged into
`~/logos-workernode-mlx/chat-templates` (where the agent points
`LOGOS_CHAT_TEMPLATE_DIR`): templates the machine does not have yet are
copied in, files you added or edited yourself are never overwritten. A
template referenced in `config.yml` therefore works out of the box after the
first bootstrap — no hand-seeding.

### Register the node

The worker needs a provider entry in Logos before it can connect. Create it in
the Logos UI (*Providers → add*, type `logosnode`) and copy the worker key it
returns.

The privacy level is not a formality — pick it by where the machine physically
stands and who can touch it:

| Level | When |
|---|---|
| `LOCAL` | Your own datacentre or server room |
| `THIRD_PARTY_HARDWARE` | Someone else's Mac, e.g. a personal laptop |

A Metal lane is a **native process on that machine**, so whoever operates it
can attach a debugger or read its logs. `LOCAL` in the router's privacy
ordering means "our datacentre", not "not a cloud" — see *Privacy* below.

Then fill in credentials and start:

```bash
cd ~/logos-workernode-mlx
cat > .env <<'ENV'
LOGOS_URL=https://logos.example.tum.de
LOGOS_API_KEY=<worker key>
HF_TOKEN=<hf token>
ENV
chmod 600 .env              # credentials — keep it owner-only
$EDITOR config.yml          # seeded from config.example.mlx.yml
launchctl kickstart -k "gui/$(id -u)/de.tum.logos.workernode"
```

The worker loads `.env` from the install root itself at startup (the
launchd plist deliberately carries no secrets — it is world-readable).
Environment variables set by the plist or your shell override the file.

### Overrides

| Variable | Default | Purpose |
|---|---|---|
| `LOGOS_MLX_HOME` | `~/logos-workernode-mlx` | install root |
| `LOGOS_MLX_IMAGE` | `ghcr.io/ls1intum/logos-workernode-mlx:latest` | image to pull |
| `LOGOS_METAL_VENV` | `~/.venv-vllm-metal` | vllm-metal venv — read by the installer *and* the runtime resolvers (vllm binary, telemetry interpreter); bootstrap passes it to the launchd agent. Upstream's installer always creates `~/.venv-vllm-metal`, so a custom path must be populated by you (e.g. upstream's editable install) |
| `LOGOS_METAL_PYTHON` | resolved from the venv | interpreter for the MLX telemetry probe |
| `LOGOS_WORKER_BACKEND` | auto (`darwin` → metal) | force `metal` or `cuda` |

---

## Worked example: serving Qwen3.8-27B

The reference model for this document is
[Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) in its MLX builds —
`mlx-community/Qwen3.8-27B-4bit` (15.1 GB) and
`mlx-community/Qwen3.8-27B-8bit` (27.5 GB). It is the model the *Sizing*
table measures, and the reason the *Requirements* table pins
vllm-metal ≥ 0.28.0. Embedding models raise that floor to 0.29.0 — see
*Embedding models* below.

The seeded `config.yml` advertises the **4bit** build by default — the only
one that fits the 36 GB reference machine. On a 64 GB+ Mac, point
`logos.capabilities_models` at the 8bit id instead. Whatever you advertise
must have two things or the lane cannot start: a hand-written profile under
`model_profile_overrides` (the measured figures from *Calibration*), and a
`model_overrides` entry capping `max_model_len` at 32768 — Qwen3.8's hybrid
KV cache would otherwise be sized against the model's full 262144 window,
which does not fit.

After the *Install* steps, start the node and follow the log:

```bash
launchctl kickstart -k "gui/$(id -u)/de.tum.logos.workernode"
tail -f ~/logos-workernode-mlx/logs/worker.log
```

Expected at startup:

```
══ STORAGE LAYOUT ══
  cache root: /Users/<you>/logos-workernode-mlx/cache  (LOGOS_WORKER_CACHE_ROOT env var)
    HF_HOME                  → /Users/<you>/logos-workernode-mlx/cache/.hf_cache
    VLLM_CACHE_ROOT          → /Users/<you>/logos-workernode-mlx/cache/.cache/vllm
    TORCHINDUCTOR_CACHE_DIR  → /Users/<you>/logos-workernode-mlx/cache/.cache/torch_inductor
    FLASHINFER_WORKSPACE_BASE→ /Users/<you>/logos-workernode-mlx/cache
```

`worker.cache_path` may use `~`; the layout line shows the expanded absolute
path, because the lanes resolve the same root themselves and a literal `~`
would be an empty directory to them.

On the first start the weights are not cached yet, so the download runs in
the background while the worker keeps registering:

```
Prefetching 1 missing capability model(s): ['mlx-community/Qwen3.8-27B-4bit']
Prefetch: downloading mlx-community/Qwen3.8-27B-4bit …
```

`Prefetch: … download complete` arrives when the weights are in. Then the
capability profile and the registration:

```
  ● mlx-community/Qwen3.8-27B-4bit [OVERRIDE]: base_residency=16680 MB | disk=15.0 GB | kv_per_token=138344 B | max_ctx=262144 | engine=vllm
══ BRIDGE CONNECTED ══ worker_id=<uuid> capabilities=['mlx-community/Qwen3.8-27B-4bit'] url=<websocket URL>
```

The profile dot is cyan for a hand-measured `override`. A red `UNCALIBRATED`
dot and `Excluding 1 uncalibrated model(s) from capabilities` instead means
the model is advertised to no one — the profile is missing or has no
`base_residency_mb` (*Troubleshooting*).

The orchestrator otherwise refuses to load a model that has never been
calibrated on the node it would run on — Metal/MLX providers are the one
exception, so an `override` profile here keeps working exactly as before.

On the orchestrator, add this Mac as a provider with the privacy level
**`THIRD_PARTY_HARDWARE`** (*Privacy* below). When a request routed there
arrives, the worker spawns the lane — a native
`vllm serve mlx-community/Qwen3.8-27B-4bit` subprocess with the Metal
plugin, which prints the memory breakdown at startup (the measured block in
*Sizing*) and reports ready. Afterwards `GET /runtime` shows the node and
its lane: `devices.mode` must be `metal`, and `total_memory_mb` the Metal
working set, not `hw.memsize`.

The example config sets `max_lanes: 1`: one model at a time. A second lane
only starts once the orchestrator stops the first — stop/start is how this
backend reclaims memory, since vLLM cannot unload weights and Metal has no
sleep mode (*What differs from a CUDA node*).

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
lane to the CPU. The tradeoff: the account has to be logged in for the agent to
run at all.

On an unattended machine enable auto-login (System Settings → Users & Groups →
Automatic login). **With FileVault enabled, auto-login is unavailable** — the
disk unlock *is* the login — so after every reboot someone has to unlock the
machine physically before the node comes back. Two ways out:

- Turn FileVault off. Reasonable for a machine in a locked server room, a
  deliberate decision anywhere else.
- Keep FileVault and use `sudo fdesetup authrestart` for planned reboots: it
  unlocks the next boot once, so a remote restart does not strand the node.
  It does not help after a power cut.

### Sleep must stay off

A MacBook idles into sleep within minutes and takes the node offline with it;
closing the lid does it immediately. `bootstrap-macos.sh` configures this
already — verify with `pmset -g | grep SleepDisabled` (must print `1`). To set
it by hand:

```bash
sudo pmset -a disablesleep 1     # covers the closed lid, which the timers below do not
sudo pmset -c sleep 0 displaysleep 0 disksleep 0 standby 0 autopoweroff 0 powernap 0
```

`disablesleep` is the load-bearing one: the per-source timers only govern idle
sleep, not the lid switch.

---

## Uninstall

```bash
~/logos-workernode-mlx/scripts/uninstall-macos.sh
```

Prints what it is about to delete and asks before doing it. Removes the launchd
agent, the install root (including `config.yml`, `.env` and the model cache),
the vllm-metal venv and the pulled image, then restores the sleep defaults so a
decommissioned laptop does not sit awake until the battery is flat.

| Flag | Effect |
|---|---|
| `--keep-cache` | Preserve `<install root>/cache` — 15 GB per 8B model that would otherwise be re-downloaded |
| `--keep-power-settings` | Leave sleep disabled |
| `--yes` | No confirmation prompt |

It deliberately leaves `~/.cache/huggingface`, Homebrew, uv and Python alone:
the worker keeps its models under the install root, so anything in a shared
cache belongs to someone else's work.

The provider entry in Logos is server-side state — remove it in the UI too, or
it lingers as a permanently disconnected node.

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

## Embedding models

Embedders need **vllm-metal ≥ 0.29.0** and `--runner pooling`, passed through
`extra_args` — the model is otherwise loaded as a text generator and exposes
completions instead of `/v1/embeddings`.

Two loading paths exist upstream, and which one a checkpoint takes decides
whether it works at all:

| Family | Path | Status |
|---|---|---|
| Encoder (BGE-M3, XLM-RoBERTa, multilingual E5) | encoder pooling, own loader — no paged attention, no KV cache | works |
| Decoder (Qwen3-Embedding) | generation loader, then pooled | works from 0.29.0 |

On 0.28.0 the decoder path failed both ways and neither error named the real
cause. The official Qwen checkpoints store the backbone flat
(`embed_tokens.weight`, `layers.0.…`) while mlx-lm's Qwen3 wraps it under
`model.`, so every tensor was rejected — `Received 398 parameters not in
model` (vllm-metal#730). The MLX re-quantizations (`-mxfp8`, `-4bit-DWQ`) got
further and then died on `Missing 1 parameters: lm_head.weight`: the
generation loader wanted a language-model head that an embedder does not
have. 0.29.0 fixes the remap; both failures are gone.

Worked example — `Qwen/Qwen3-Embedding-8B` on a 32 GB M2 Pro, measured:

```yaml
logos:
  capabilities_models:
    - "Qwen/Qwen3-Embedding-8B"

engines:
  vllm:
    model_overrides:
      "Qwen/Qwen3-Embedding-8B":
        tensor_parallel_size: 1
        max_model_len: 32768        # native window is 40960
        mm_processor_cache_gb: 0
        # The pooling runner has no chat-completions path, so the flags the
        # worker adds by default would reach a server that cannot use them.
        enable_auto_tool_choice: false
        reasoning_parser: "none"
        # Prefix caching is a decode-path optimization; a pooling request is
        # a single-pass encode with nothing to reuse.
        enable_prefix_caching: false
        extra_args: ["--runner", "pooling"]

model_profile_overrides:
  "Qwen/Qwen3-Embedding-8B":
    base_residency_mb: 15400        # (15.13 + 0.64) GB -> 15039 MiB, rounded up
    kv_per_token_bytes: 147456      # 36 layers x 2 x 8 kv_heads x 128 head_dim x 2 B
    max_context_length: 32768
    disk_size_bytes: 15134634568
```

**The lane's log reports decimal GB, not GiB** — worth knowing before converting
any of these numbers. Proof from the same machine: MLX reports
`max_recommended_working_set_size = 26800603136` bytes, which is 26.80 GB
decimal (24.96 GiB), and the lane logs `metal_limit=26.80GB`. So
`base_residency_mb` is `(15.13 + 0.64) x 10^9 / 1024^2 = 15039 MiB`, rounded up
to 15400. Reading those figures as GiB would inflate the profile by about
1.1 GB and reject placements that in fact fit.

That lane reports `usable_metal=22.78GB`, `kv_budget=7.00GB` and
`max_tokens_cached=47488` — 1.45x concurrency at the full 32k window. It
answers `/v1/embeddings` with 4096-dimensional vectors.

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
neither of which exists on macOS. Calibration is therefore unavailable on the
Metal backend *by construction* — no flag to set: the worker refuses
server-driven calibration sessions automatically (the refusal carries
`reason_code=metal-backend`), and its startup calibration path skips itself.
Provide `model_profile_overrides` by hand instead; a profile with
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

This is the shape of deployment that [Darkbloom](https://www.darkbloom.dev/)
runs at scale — idle Apple Silicon serving production traffic as ordinary
fleet nodes. The *Worked example* above is that deployment on a single
machine, and it is what this PR ships: the worker, the lanes, the telemetry,
and the `THIRD_PARTY_HARDWARE` tier that makes routing onto hardware outside
operator control opt-in. Darkbloom additionally layers hardware attestation
on top (keys generated in the Secure Enclave, requests decryptable only on
the attested machine, debugger attachment blocked); that cryptography is
orthogonal to the worker and out of scope here — the trust tier above closes
the routing gap without it.

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

**`Could not obtain a pull token` / manifest fetch fails.** The bootstrap
pulls anonymously, which only works while the GHCR package is public (Package
settings → Change visibility). For a private package, fetch the token with
credentials instead:
`curl -u <user>:$GITHUB_TOKEN "https://ghcr.io/token?scope=repository:ls1intum/logos-workernode-mlx:pull"`

---

## Version pinning

The installer and everything it executes or installs are pinned to a
release tag **plus SHA256 checksums** in `install-macos.sh`
(`VLLM_METAL_REF` and the four `*_SHA256` constants) — not to `main` or
`/releases/latest`. This is an ordinary supply-chain concern for a CI
image, but a sharper one here: the installer executes on a contributor's
personal Mac, which is also the machine that will hold other people's
prompts in memory. A moving `main` can change the venv layout, the CLI
flags the worker builds against, or the wheel set it resolves — and the
worker would only notice when lanes stop starting. What runs must be
exactly the bytes the checksums describe.

At the pinned release, upstream's `install.sh` only checksums itself and
then performs three further fetches: it sources `scripts/lib.sh` from the
mutable `main` branch (executed code), selects the vllm-metal wheel from
`/releases/latest`, and derives the vLLM core wheel URL from a release
lookup. `install-macos.sh` therefore fetches all four artifacts —
installer, `lib.sh`, vLLM core wheel, vllm-metal wheel — from the pinned
tag, verifies each SHA256 *before* the installer runs, stages them, and
rewrites exactly those statements in the installer to point at the staged
copies (exact-string patch, fail-loud: if upstream changed a line, the
install aborts instead of running a half-patched installer). The staged
installer is kept as a plain file in its own directory: a `scripts/lib.sh`
sibling would switch upstream into its source-checkout branch. The venv is
still created by the upstream installer, which installs a matched
(vllm, mlx, torch) set — the pinned release gives vLLM 0.29.0, the same
release the CUDA image pins. PyPI carries no macOS vLLM wheel, and pulling
that set apart in our own requirements file is how you get an unbootable
lane. And the installer's version floor (`VLLM_METAL_MIN_VERSION`, asserted
against the installed distribution on every run) makes the documented
requirement enforceable instead of aspirational.

That is why `MetalVllmProcessHandle` builds its own command line instead of
filtering the CUDA one, and why `tests/test_metal_process.py` cross-checks the
generated flags against the *installed* vllm-metal whenever the suite runs on a
Mac. `logos_update-vllm.yml` only touches `Dockerfile`, not `Dockerfile.mlx`,
so automated vLLM bumps do not reach this path — `logos_update-vllm-metal.yml`
is the one that does (below).

Keep vllm-metal current. It moves fast and dev builds are published daily —
but upstream prunes old dev releases, so the pin is the **stable** cut:
v0.29.0 is the current stable release. Note that the two measurement sets in
this document come from different runtimes: the *Sizing* table was measured on
vllm-metal 0.3.0.dev20260826 (a 36 GB M3 Pro), the *Embedding models* profile
on v0.29.0 (a 32 GB M2 Pro). Re-measure on the runtime you actually deploy
rather than mixing them. Qwen3.8 support landed in 08/2026,
and 0.2.0 could not serve it at all; embedding models need 0.29.0.

**The bump is automated.** `.github/workflows/logos_update-vllm-metal.yml`
runs daily (and on demand, with an optional version input): it picks the newest
stable vllm-metal release, downloads its `install.sh`, its `scripts/lib.sh`,
its release wheel and the vLLM core wheel it names, recomputes all four
SHA256s, re-verifies that the four exact-string patch patterns still match
exactly once each, updates `VLLM_METAL_REF`, the wheel names and URLs and
`VLLM_METAL_MIN_VERSION` together, and opens a PR. If a patch pattern no
longer matches, it fails loudly instead of opening a PR that would produce a
half-patched installer — that case needs a human.

To do it by hand, the same steps apply: download those four artifacts from the
target tag, compute the SHA256s, update `VLLM_METAL_REF` **and all checksums**
together in `install-macos.sh`, bump `VLLM_METAL_MIN_VERSION` if the new floor
applies, re-check the patch patterns, and re-run the script — it is idempotent.
Do not pipe a fetched installer into bash: verify the checksum first, as the
installer now does for itself.

Note that `install.sh` and `scripts/lib.sh` are frequently byte-identical
across tags (they were between v0.28.0 and v0.29.0), so two of the four
checksums often do not change. Confirm that by recomputing them — never assume
it.

Upgrading a node that is already deployed is just a re-run of
`bootstrap-macos.sh`: it fetches the current image, replaces the code and the
runtime, and leaves `config.yml`, `.env`, `data/`, `logs/` and `cache/` alone.

Two things to re-check after an upgrade, both of which changed between 0.2.0
and 0.3.0.dev: the `VLLM_METAL_*` names in `MetalConfig`
(`VLLM_METAL_BLOCK_SIZE` and `VLLM_METAL_PREFIX_CACHE*` were removed), and
whether any flag the worker emits has been renamed — the cross-check test
covers the second.
