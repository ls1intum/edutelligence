# Configurable model benchmarks

The Models → Performance runner supports public Hugging Face datasets with a plain-text prompt column. Search selects a repository; configuration, split and prompt column are loaded from the HF Dataset Viewer. Private/gated datasets and structured conversation or multimodal columns are not supported by this editor.

## Start and confirm a run

Open **Models → Model Management → model → Performance** as a Logos admin.
Select the worker/provider, dataset, sample size and serving settings.
Select **Review & start benchmark** to open the shared confirmation dialog.
The dialog uses the same `app-modal-confirm` component as team deletion.
Only **Start benchmark** submits the job; **Cancel** or closing the dialog does not start it.
For a batch, one confirmation starts all configurations and repetitions.

The dialog explains whether the target model lanes will be reserved.
It also explains that changed vLLM settings remain active after the run.
External provider benchmarks run alongside other requests; their traffic can affect the measurements.

## Automatic lane reservation

For an internal Logos worker benchmark, the orchestrator reserves the selected
provider/model pair before the background job starts. The reservation covers all
lanes for that model on that worker, including replacement lanes and gaps between
batch runs. It is temporary; there is no persistent benchmark-only lane setting.
Other models on the same worker remain available.

- Existing admitted requests finish before measurement starts. Preparation checks
  both locally tracked requests and the worker's lane counters. A drain timeout
  fails preparation instead of starting measurement with those requests active.
- New production requests cannot reserve capacity or select a reserved model lane.
  They wait in the normal queue or use another eligible provider, subject to normal
  request limits and timeouts. The transport checks ownership again before sending
  inference commands, including streaming requests.
- Benchmark requests use a signed, job-scoped internal endpoint. After authentication,
  the orchestrator registers each request ID with the reservation. This access lasts
  through request processing and ends when the request completes.
- The capacity planner skips planned changes to the reserved model. Benchmark
  preparation can still load, wake and configure its lane.
- Completion, failure and cancellation release ownership through the job's task
  cleanup callback. Releasing a reservation does not restore previous vLLM settings.

The worker must be connected and must have sent its first status report.
Capacity planning must be available. Otherwise, the start endpoint rejects the run.
Only one benchmark job is admitted per provider at a time.

Reservation ownership is held in orchestrator memory, matching the existing
single-process benchmark execution model. It is not a distributed lock across
multiple orchestrators. Worker disconnects and orchestrator restarts stop the job;
a batch does not resume automatically after a restart.

Implementation entry points:

| Responsibility | Source |
| --- | --- |
| Ownership and authenticated request IDs | [`BenchmarkReservations`](../src/logos/benchmarks/reservations.py) |
| Acquire ownership and authenticate benchmark traffic | [`internal.py`](../src/logos/routers/internal.py) |
| Capacity admission and request completion | [`logosnode_facade.py`](../src/logos/sdi/logosnode_facade.py) |
| Keep production entries queued during reservation | [`base_scheduler.py`](../src/logos/pipeline/base_scheduler.py) |
| Lane selection and final transport check | [`logosnode_registry.py`](../src/logos/logosnode_registry.py) |
| Drain requests and prepare the model | [`capacity_planner.py`](../src/logos/capacity/capacity_planner.py) |
| Release ownership when the job task finishes | [`main.py`](../src/logos/main.py) |

## Data loading

The default remains `openai/gsm8k`, configuration `main`, split `test`, prompt column `question`. Search and schema discovery query Hugging Face metadata APIs; the browser does not download the dataset. When the job starts, GuideLLM 0.7.2 uses `datasets.load_dataset` on the orchestrator. This downloads/prepares data and reuses the Hugging Face cache on subsequent runs while that cache exists. The dataset is not bundled in the Logos image. Cache survival across container replacement depends on deployment storage; the code does not guarantee it. A small sample count limits benchmark requests, not necessarily the volume downloaded by the datasets library.

These are serving-performance benchmarks. Choosing GSM8K supplies its questions as prompts; Logos does not grade answers against the dataset's reference answers.

The picker shows a scrollable preview of the first five entries in the selected
configuration/split, including the prompt and available reference-answer fields.
It reuses the HF Viewer `first-rows` response already fetched for column discovery;
there is no additional dataset download. Each cell is limited to 2,000 characters,
with truncation indicated in the UI. Structured answers are displayed as plain
JSON text. These are dataset examples, not generated model responses or a promise
that the benchmark's seeded sample will contain these exact rows.
**Open in Hugging Face** opens the full viewer for the current configuration/split
in a new tab and stays available if the preview cannot load.

## Next-run settings

A historical result's Configuration section offers **Use for next benchmark**. It copies captured settings into an independent editable draft, including vLLM values. Stored benchmark results are unchanged. Samples (1–100), maximum output tokens (1–4096), sequential/concurrent profile (1–32 streams), seed and dataset mapping are editable. Tool version, measured worker strategy and the recorded command remain historical information.

vLLM overrides apply only to Logos workers. Blank fields keep the current worker value; explicit false is preserved. The orchestrator prepares an idle lane, prevents routing during reconfiguration, merges the selected overrides, and asks the worker to reload. The worker checks its active-request counters under the lane lock before restarting. The orchestrator waits for the updated configuration to appear in worker status before measuring. Unsupported settings, worker errors and timeouts fail the job instead of recording a successful run. When retrying a failed lane with corrected settings, the new configuration is applied before another startup attempt.

Changed vLLM settings remain active after the benchmark, including if measurement fails or is cancelled after reconfiguration. There is no automatic rollback. Deploy the updated workernode together with the orchestrator to enforce the `require_idle` reconfiguration guard.

`attention_backend` can be fixed for a run or varied in a batch: `FLASHINFER`,
`FLASH_ATTN`, `TRITON_ATTN`, `FLEX_ATTENTION`, and `TURBOQUANT`. An empty
override preserves the worker setting. Explicit choices use the existing worker
`--attention-config.backend` flag and are recorded with the benchmark, so
comparisons of other parameters do not mix different attention settings.
Support depends on the installed vLLM version, GPU, model and cache format;
an incompatible choice fails preparation instead of silently falling back.
`TURBOQUANT` requires a `turboquant_*` KV cache dtype; the editor exposes those
formats and validates that prerequisite before starting. The backend priority
tables in the [vLLM documentation](https://docs.vllm.ai/en/latest/design/attention_backends/)
describe automatic selection, not a performance ranking for every model.

## API

All Spring endpoints below require `logos_admin` and forward to the internal orchestrator API using the existing internal authentication:

- `POST /logosdb/model_benchmarks/datasets/search`: `{ "query": "gsm8k" }`
- `POST /logosdb/model_benchmarks/datasets/metadata`: `{ "dataset": "openai/gsm8k", "subset": "main", "split": "test" }` (subset and split are optional)
- `POST /logosdb/model_benchmarks/run`: existing target and sample fields plus `dataset`, `subset`, `split`, `text_column`, `profile`, `concurrency`, `seed` and optional `serving_overrides`.

The selected settings are persisted with the job; successful results store the actual GuideLLM scenario and the worker's serving snapshot. No database migration is required.


## Benchmark batches and comparison

Enable **Run a batch**, choose repetitions per configuration, and add parameters to vary. Numeric parameters accept a comma-separated list or a From/To/Step range; boolean parameters accept `true, false`. Multiple varied parameters produce all combinations. The preview lists each configuration and the fixed settings before starting. Concurrency sweeps use the concurrent profile, including the one-stream case. Limits are 1,000 configurations and 10,000 total runs, independent of the sample count per run.

The start confirmation uses the same modal dialog as team deletion. Confirming once submits the complete plan to the server; closing the browser does not stop execution. Each configuration is repeated before advancing to the next one. One provider lease covers the whole batch, with progress and one cancel action. On Logos workers, the selected model’s lanes are reserved for the job, including the intervals between repetitions and configurations. Existing requests drain before measurement; production requests remain queued or use another provider. Other models on the worker remain available. The reservation is released on completion, failure, or cancellation. The capacity planner does not reclaim the reserved lanes. The first failed run stops the remaining batch; completed measurements stay stored. Worker disconnects and orchestrator restarts stop the batch under the existing lease rules; batches do not resume automatically after a server restart. Serving overrides remain applied, as for a single run.

The existing run endpoint accepts optional `batch: { configurations: [...], repetitions: 3 }`. Every configuration contains the same settings as a single run, using `samples` (1–100) inside the batch. Configurations are complete settings, not patches to the outer request. All configurations and their hardware limits are validated before a job is created. Every changed serving key must be present in every configuration to avoid inheriting a prior run's value. The job result exposes `total_runs`, `run_index` (one-based), `completed_runs`, `configuration_index`, and `repetition`.

The two comparison charts sit side by side on desktop and stack on narrow screens. Each Y-axis fits its own measured range, including outliers, with 10% of that range added above and below; identical measurements use 10% of their magnitude (or 1 for zero) as padding. Each box summarizes run-level measurements for one parameter value, with all other recorded controls matching the reference. Quartiles use linear interpolation; whiskers reach the last observations within 1.5 times the interquartile range. Dots show outliers, `n` counts captured measurements, and a single measurement appears as a filled point. These are distributions across runs, not pooled request latencies. The individual-run table is collapsed and loads 50 rows at a time.

### GPU restrictions and failed runs

The benchmark editor shows GPU names and CUDA compute capabilities reported by the worker.
FLASHINFER and FLASH_ATTN are unavailable on reported pre-Ampere GPUs (SM below 8.0).
The same restriction is enforced when submitting a benchmark, including inherited worker settings.
Other backends are labelled unverified: passing this GPU check does not establish model, cache,
installed-library or runtime compatibility. Missing architecture telemetry does not imply incompatibility.

A failed run records its configuration, selected attention backend and diagnostic text. The worker
preserves useful exception lines ahead of generic engine shutdown messages. The UI exposes these
under **View error details & configuration**; historical records may contain only the old truncated error.
Batches still stop at the first failed run. There is no automatic retry or backend probing.

When an admin starts another run with serving overrides, an existing `error` or
`stopped` lane receives the selected configuration before another startup attempt.
This avoids retrying the old failed configuration first. A failed lane also proceeds
through preparation when the requested settings match the stored settings; it is not
considered ready merely because the settings are unchanged. The worker must report
the applied configuration and a ready lane before measurement starts.

This ordering does not repair an offline worker, unsupported model/backend combination,
or insufficient GPU memory. Inspect **View error details & configuration**, correct the
cause, and start another run.

**Load comparison preset** fills the comparison template; **Clear vLLM changes** removes draft
serving overrides, and **Stop varying** removes a parameter from the sweep. These actions do not
restore settings already applied to a worker.

### Single-run results

A single eligible result is plotted as a filled point for each metric, including
when batch repetitions is 1. The label `n = 1` counts one measured run, not one
request: that run can contain many samples. Repeated measurements use a boxplot.
A single result can therefore appear in both comparison charts without another
parameter value to compare. No additional comparison result is fabricated.

Comparisons still require the recorded configuration controls and a successful,
complete result. Incomplete historical metadata is not inferred. If a stored
result is absent from a chart, check its completion state and recorded controls.

## Dev verification

Use a connected GPU worker with a ready model for the following checks.
The CI forwarding-overhead benchmark uses a mock lane; it does not replace this test.

1. Start a normal request, then confirm a benchmark for the same provider/model.
   Verify that the existing request finishes before measurement starts.
2. Send new production requests during the benchmark. Verify that they wait or use
   another eligible provider, while benchmark requests continue successfully.
3. Run one configuration with one repetition. Verify a filled point and `n = 1`
   in the comparison charts for each available metric.
4. Run multiple configurations and repetitions. Verify that the reservation remains
   active between runs and that the first failure stops the remaining batch.
5. Cancel a running job. Verify that production requests can use the model again
   after cleanup. Repeat the release check after successful and failed jobs.
6. For a lane that failed to start, correct its serving settings and submit another
   run. Verify that reconfiguration precedes startup and the lane reaches ready state.
7. Verify that the applied vLLM settings remain active after completion or cancellation.
   Restore the intended serving settings explicitly if required.
