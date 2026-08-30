# LogosWorkerNode

LogosWorkerNode is the outbound worker for local inference in Logos.

It does four things:
- starts one lane process per configured model,
- keeps a websocket session open to Logos,
- reports runtime/device/lane status so Logos can schedule against warm/cold capacity,
- auto-calibrates model memory profiles (observed reservation, base residency, sleeping residual) and persists them across restarts.

## Configuration split

| Source | What | Managed by |
|---|---|---|
| `.env` | Credentials (`LOGOS_URL`, `LOGOS_API_KEY`) | GitHub secrets/variables |
| `config.yml` | Hardware & tuning (capabilities, vLLM overrides, engine settings) | Ansible |
| `chat-templates/` | Custom Jinja chat templates (see below) | Ansible |
| `/app/data/` | Runtime state (lanes, model profiles) | Auto-managed (Docker volume) |

No overlap. Credentials never go in `config.yml`. Hardware config never goes in `.env`.

## Custom chat templates

A model can be served with a chat template other than the one bundled with its
tokenizer. Templates live in a persistent, operator-managed directory —
`/opt/logos-workernode/chat-templates` on the host, bind-mounted read-only into
the container at the *same* absolute path, so config, logs and the vLLM command
line all name one path.

```yaml
engines:
  vllm:
    model_overrides:
      Qwen/Qwen3-8B:
        chat_template: qwen3-tools.jinja   # file name, not a path
```

The worker resolves the name against the template directory and passes the
absolute path to vLLM as `--chat-template`. Values escaping the directory
(`..`, absolute paths pointing elsewhere) are rejected, and a missing file
fails the lane spawn with an explicit error instead of silently reverting to
the model's built-in template.

Adding or editing a template needs no redeploy — the deploy workflow only ships
`docker-compose.yml` and `.env` — just drop the file on the host and restart the
lane. Set `LOGOS_CHAT_TEMPLATE_DIR` to relocate the directory (local dev, tests).

## GGUF models (vLLM lanes)

vLLM lanes can serve GGUF repositories. vLLM's GGUF quantization lives in the
out-of-tree `vllm-gguf-plugin` (installed in GPU worker images); the worker
auto-detects GGUF models and resolves what to serve:

- `unsloth/Qwen3-8B-GGUF` — bare repo; the worker lists its `.gguf` files
  (local HF cache first, HuggingFace Hub as fallback) and picks `Q4_K_M` when
  available, otherwise a deterministic fallback order.
- `unsloth/Qwen3-8B-GGUF:Q4_K_M` — explicit quant.
- `unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf` — explicit file; multi-file
  shard sets (`…-00001-of-00004.gguf`) are read natively by the plugin, no
  merge step needed.

The lane keeps answering under the model name it was registered with (the
served reference is aliased back via `--served-model-name`). To pin the quant
or pass the base model's tokenizer (recommended by vLLM, also the HF config
source for the GGUF loader), use `engines.vllm.model_overrides` — see
`gguf_quant` / `gguf_tokenizer` in `config.example.yml`. Startup prefetch
downloads only the selected quantization's files, not the whole multi-quant
repository.

**The plugin loads into every vLLM process, not just GGUF lanes.**
`vllm-gguf-plugin` registers through vLLM's `vllm.general_plugins` entry
point, which vLLM evaluates on *every* engine start. Its `register()` is not
passive: it registers the GGUF quantization, loader, and config parser and
applies three monkey-patches over vLLM internals (`EngineArgs`, the
speculator-override hook, the diffusers loader). Those wrappers therefore run
inside every lane on the node — AWQ, safetensors, and GGUF alike — and are a
no-op only because they detect GGUF references and pass through otherwise. A
bug in the plugin (pinned at `vllm-gguf-plugin==0.0.5` in the GPU image)
reaches every lane, not only GGUF ones. The worker's own GGUF handling is
still gated to lanes that actually resolve to a GGUF reference; the global
registration is the plugin's, not the worker's.

**Calibrate before you route.** A GGUF model is not routable the moment it is
configured. Until the worker has calibrated it, its capability is reported as
`UNCALIBRATED` (no `base_residency_mb` yet) and is excluded from the
capabilities the worker advertises — so the orchestrator never sees the model
and never requests a lane for it. Run calibration for the model first (the
nightly session or a targeted run); once a profile exists it advertises and
placement proceeds as for any other calibrated model. The `kv_budget` /
`gguf_quant` overrides land immediately, but they take effect on routing only
after the model is calibrated back into the advertised set.

## Storage layout

The worker uses **one persistent volume** for everything that benefits from
surviving container restarts: model weights and four compilation/JIT caches.
All five hang off a single root, resolved at boot:

1. `LOGOS_WORKER_CACHE_ROOT` env var if set (operator/CI override, e.g. via
   `.env`).
2. otherwise `worker.cache_path` from `config.yml` (recommended config-file
   knob — see `config.example.yml`).
3. otherwise `engines.ollama.models_path` (default in `config.yml`:
   `/usr/share/ollama/.ollama/models`) — used because the standard
   `docker-compose.yml` already mounts that path as a named volume
   (`ollama-models`).

Layout under `<root>/`:

| Subpath | What | Set via | Why persistent |
|---|---|---|---|
| `.hf_cache/hub/models--*/blobs/` | HuggingFace model weights | `HF_HOME` | downloads happen once per model |
| `.cache/vllm/` | vLLM compilation artifacts | `VLLM_CACHE_ROOT` + `--compilation-config cache_dir` | torch.compile bytecode reuse |
| `.cache/torch_inductor/` | Torch inductor / FX graph cache | `TORCHINDUCTOR_CACHE_DIR` (+ `TORCHINDUCTOR_FX_GRAPH_CACHE=1`) | inductor lowering cache |
| `.cache/flashinfer/<version>/<sm>/cached_ops/*.so` | FlashInfer JIT kernels (per-`(head_dim, dtype)`) | `FLASHINFER_WORKSPACE_BASE` (parent of `.cache/flashinfer`) | first compile takes 30–60 s; reused thereafter |
| (ollama's own GGUF blobs, if Ollama is configured) | Ollama models | `OLLAMA_MODELS` | when Ollama lanes are in use |

**Default deployment** — leave both `LOGOS_WORKER_CACHE_ROOT` and
`worker.cache_path` unset; everything defaults to
`engines.ollama.models_path` and is preserved by the `ollama-models`
named volume in `docker-compose.yml`. This is the expected setup for
ASE/Ansible deployments.

**Non-ollama deployment** — set `worker.cache_path: /var/cache/logos-worker`
(or any persistent path) in `config.yml` and mount that path as a Docker
volume. All four caches relocate together, ollama remains optional.

**Operator override** — set `LOGOS_WORKER_CACHE_ROOT=/some/path` in `.env`
to override `config.yml` for a particular host without editing the
config file.

**Per-cache override** — any of `HF_HOME`, `VLLM_CACHE_ROOT`,
`TORCHINDUCTOR_CACHE_DIR`, `FLASHINFER_WORKSPACE_BASE` can be set
individually to override just one cache (precedence is per-env-var > root).

### FlashInfer pre-warmup

Worker boot runs `flashinfer_warmup.py` once before any vLLM lane spawns.
It compiles the kernels vLLM uses at runtime (`single_prefill_with_kv_cache`
and `batch_prefill_with_kv_cache`) for each capability model's head shape
and writes them to `<root>/.cache/flashinfer/<version>/<sm>/cached_ops/`.
The boot log line confirms reuse:

```
FlashInfer warmup completed in 0.3s (single_prefill=3/3, batch_prefill=1/1, 2 kernels resident on disk, +0 new this boot)
```

`+0 new this boot` means every kernel was already on disk and reused.
A non-zero value indicates either a fresh worker or a new model head shape.

## Local dev
1. Copy `.env.example` to `.env` and fill in connection credentials.
2. Edit `config.yml` for capabilities and engine settings.
3. Start the worker:
```bash
docker compose -f docker-compose.dev.yml up --build
```
4. Check health:
```bash
curl http://localhost:8444/health
```

## GPU worker
Use the production compose file when the host exposes NVIDIA runtime support:
```bash
docker compose up -d
```

vLLM requirement:
- vLLM lanes require a working `nvidia-smi`.
- LogosWorkerNode blocks vLLM startup when `nvidia-smi` is unavailable or misconfigured.
- If you want to run without `nvidia-smi`, use Ollama lanes only.

## Docs
- Setup: [QUICKSTART.md](QUICKSTART.md)
- Lane operations: [LANES.md](LANES.md)
- Validation and test commands: [TESTING.md](TESTING.md)
- Benchmark scripts and API collections: `tools/`
- Research notes and benchmark outputs: `research/`
