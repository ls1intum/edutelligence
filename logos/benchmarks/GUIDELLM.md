# GuideLLM → Logos

This is the smallest end-to-end path for one GSM8K provider-model benchmark:

```text
provider-model pair → GuideLLM → benchmarks.json → Logos import endpoint → Performance tab
```

## Run from Logos

For the admin workflow, use **Models → Model Management → model → Performance → Run benchmark**.
Follow the [Model Benchmarks guide](../docs/admin/model-benchmarks.md) for configuration,
confirmation, results and screenshots.

The commands below remain available for local diagnosis and manual imports.
They do not create an internal benchmark job or acquire its lane reservation.
Requests sent to Logos through a public endpoint remain normal production requests.
See [Configurable model benchmarks](../logos-orchestrator/docs/benchmark-configuration.md)
for the orchestrator's reservation and API behavior.

## Setup

GuideLLM requires Python 3.10–3.13. From `logos/benchmarks`:

```bash
uv venv --python 3.13 .venv-guidellm
source .venv-guidellm/bin/activate
uv pip install -r requirements-guidellm.txt
```

## Run and import into Logos

Set both variables in the same terminal before starting the runner. The first key
authenticates benchmark requests against the target endpoint. The second token is
only used to import a successful result into Logos:

```bash
export MODEL_PROVIDER_API_KEY='<provider-token>'
export LOGOS_BENCHMARK_TOKEN='<logos-admin-token>'

python run_guidellm_gsm8k.py \
  --model-provider-id 42 \
  --target 'https://provider.example/v1' \
  --model 'Qwen/Qwen3-8B'
```

## Run without importing

To measure Logos Dev without importing results, use its API key:

```bash
export MODEL_PROVIDER_API_KEY='<logos-dev-api-key>'

python run_guidellm_gsm8k.py \
  --no-import \
  --target 'https://logos-dev.aet.cit.tum.de/v1' \
  --model 'Qwen/Qwen2.5-Coder-7B-Instruct-AWQ' \
  --samples 5
```

For a local endpoint without authentication or result import, no token is required:

```bash
python run_guidellm_gsm8k.py \
  --no-import \
  --no-provider-auth \
  --target 'http://localhost:8000/v1' \
  --model 'Qwen/Qwen3-8B' \
  --samples 5
```

The runner uses 100 GSM8K test questions with a synchronous profile by default. It
keeps summary metrics only, creates a unique result directory for every run, removes
the temporary credential file, and imports only a completely successful result. On
macOS it uses GuideLLM's `spawn` multiprocessing mode to avoid unsafe process forks.
Failed or incomplete reports are kept for diagnosis but produce a non-zero exit code.
