# GuideLLM → Logos

This is the smallest end-to-end path for one GSM8K provider-model benchmark:

```text
provider-model pair → GuideLLM → benchmarks.json → Logos import endpoint → Performance tab
```

## Run from Logos

For the normal admin flow, open **Models → Model Management → model → Performance**.
Select the provider-model pair and configure the run. The default dataset is GSM8K
`main/test`, with 50 samples and at most 512 output tokens per request.
Select **Review & start benchmark**, then confirm **Start benchmark** in the dialog.
The page shows live job status and adds successful results automatically.

Logos worker runs use a signed, job-scoped internal endpoint. They need no benchmark
endpoint or API key under **Providers**. The selected model's lanes are reserved
while the job runs, including all batch repetitions. Existing requests finish first;
new production requests wait or use another eligible provider. Completion, failure
and cancellation release the reservation. Other models on the worker remain available.
External provider runs use their configured server-side endpoint and credential;
Logos does not reserve their serving capacity.

One eligible measurement appears as a filled point in the comparison charts.
When retrying a failed lane with serving overrides, Logos applies the selected
settings before attempting startup. Applied settings remain active after the run.

See [Configurable model benchmarks](../logos-orchestrator/docs/benchmark-configuration.md)
for batch behavior, comparison requirements, reservation limits and the Dev checklist.

### Performance page preview

The desktop example shows the run settings and one completed measurement as a
filled point in each comparison chart. It uses synthetic data in the actual UI
component, without live services or the authenticated application shell.

![Benchmark settings and single-run results on desktop](https://gist.githubusercontent.com/Tim0x54/72219bc2b43197e7ddbeeae1029c6fd4/raw/86590c8c73b36a555202752af495cdd7f7dbba13/logos-pr-desktop.png)

See the [desktop and mobile screenshots](../logos-orchestrator/docs/benchmark-configuration.md#screenshots)
for the complete page and confirmation dialog in both viewport sizes.

The commands below remain available for local diagnosis and manual imports.
They do not create an internal benchmark job or acquire its lane reservation.
Requests sent to Logos through a public endpoint remain normal production requests.

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

For the current test against Logos-dev, only its API key is required:

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
