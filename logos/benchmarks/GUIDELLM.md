# GuideLLM → Logos

This is the smallest end-to-end path for one GSM8K provider-model benchmark:

```text
provider-model pair → GuideLLM → benchmarks.json → Logos import endpoint → Performance tab
```

## Setup

GuideLLM requires Python 3.10–3.13. From `logos/benchmarks`:

```bash
uv venv --python 3.13 .venv-guidellm
source .venv-guidellm/bin/activate
uv pip install -r requirements-guidellm.txt
```

## Run

Keep both tokens outside Git:

```bash
export MODEL_PROVIDER_API_KEY='<provider-token>'
export LOGOS_BENCHMARK_TOKEN='<logos-admin-token>'

python run_guidellm_gsm8k.py \
  --model-provider-id 42 \
  --target 'https://provider.example/v1' \
  --model 'Qwen/Qwen3-8B'
```

For a local endpoint without authentication, omit `MODEL_PROVIDER_API_KEY` and add
`--no-provider-auth`.

The runner uses 100 GSM8K test questions with a synchronous profile by default. It
keeps summary metrics only, creates a unique result directory for every run, removes
the temporary credential file, and imports only a completely successful result.
