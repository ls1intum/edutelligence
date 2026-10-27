# Configurable model benchmarks

This guide covers the internal benchmark API, lane reservations and implementation.
For the user workflow, see [Model Benchmarks](../../docs/admin/model-benchmarks.md).

## Start and confirm a run

In **Performance → Run benchmark**, **Review benchmark** or **Review batch**
opens the shared `app-modal-confirm` dialog. Only **Start benchmark** submits the job.
One confirmation starts all configurations and repetitions in a batch.
External provider benchmarks do not reserve serving capacity.

## User guide and screenshots

The published [Model Benchmarks guide](../../docs/admin/model-benchmarks.md)
contains the user workflow and complete desktop screenshots.

## Automatic lane reservation

For an internal Logos worker benchmark, the orchestrator reserves the selected
provider/model pair before the background job starts, even if no lane exists yet.
The reservation covers all lanes for that pair, including newly created lanes,
replacement lanes and gaps between batch runs.
The worker node loads the model and executes requests; the orchestrator enforces the reservation.
It is temporary; there is no persistent benchmark-only lane setting.
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

## Manual runs and nightly runs

This guide describes the manual runner and its batches. The
[nightly rotation](../../docs/admin/nightly-benchmarks.md) is a separate opt-in schedule on the
same Performance tab.

| Behavior | Manual runner | Nightly rotation |
|---|---|---|
| Selection | Admin selects a pair and starts a run or batch | Up to 2 enabled, available pairs per night; oldest attempts first |
| Workload | Editable dataset, sample count and request settings | GSM8K main/test, 50 requests, 512 max output tokens, concurrency 4, seed 42 |
| Parameter search | Admin's overrides or batch sweep | Baseline and ±25% variants of known sequence/batch-token limits |
| Admission window | Explicit admin start | 05:00–07:50 Europe/Berlin, including retries |
| Failure handling | Failed batch stops its remaining runs | One retry after a stall; skip the configuration after another stall |
| After the run | Applied serving overrides remain active | Restore the original production configuration |

The dataset editor and its question previews do not configure nightly runs.
During nightly execution or pending worker recovery, the orchestrator rejects
new manual benchmarks. Existing manual benchmarks finish before nightly admission.

## Data loading

The default is `openai/gsm8k`, configuration `main`, split `test`, prompt column `question`.
The editor supports public datasets with a plain-text prompt column.
Private or gated datasets and structured conversation or multimodal columns are not supported.
Search and schema discovery use Hugging Face metadata APIs.
GuideLLM 0.7.2 downloads the dataset on the orchestrator when the job starts.
It reuses the Hugging Face cache while that cache exists.
Cache persistence across container replacement depends on deployment storage.
A small sample count limits requests, not necessarily the download size.

These are serving-performance benchmarks. Choosing GSM8K supplies its questions as prompts; Logos does not grade answers against the dataset's reference answers.

The picker shows a scrollable preview of the first five entries in the selected
configuration/split, including the prompt and available reference-answer fields.
It reuses the HF Viewer `first-rows` response already fetched for column discovery;
there is no additional dataset download. Each cell is limited to 2,000 characters,
with truncation indicated in the UI. Structured answers are displayed as plain
JSON text. These are dataset examples, not generated model responses or a promise
that the benchmark's seeded sample will contain these exact rows.
**View on Hugging Face** opens the full viewer for the current configuration/split
in a new tab and stays available if the preview cannot load.

## Next-run settings

A historical result's Configuration section offers **Use for next benchmark**. It copies captured settings into an independent editable draft, including vLLM values. Stored benchmark results are unchanged. Samples (1–100), maximum output tokens (1–4096), sequential/concurrent profile (1–32 streams), seed and dataset mapping are editable. Tool version, measured worker strategy and the recorded command remain historical information.

vLLM overrides apply only to Logos workers. Blank fields keep the current worker value; explicit false is preserved. The orchestrator prepares an idle lane, prevents routing during reconfiguration, merges the selected overrides, and asks the worker to reload. The worker checks its active-request counters under the lane lock before restarting. The orchestrator waits for the updated configuration to appear in worker status before measuring. Unsupported settings, worker errors and timeouts fail the job instead of recording a successful run. When retrying a failed lane with corrected settings, the new configuration is applied before another startup attempt.

For manual runs, changed vLLM settings remain active after the benchmark, including if measurement fails or is cancelled after reconfiguration. There is no automatic rollback. Deploy the updated workernode together with the orchestrator to enforce the `require_idle` reconfiguration guard.

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

The job stores the selected settings.
Successful results store the actual GuideLLM scenario and the worker's serving snapshot.
Pipeline parallelism uses the worker's effective value, including global flags and lane overrides.
For older workers, explicit lane flags remain usable. Missing values remain unknown instead of defaulting to 1.

The manual configuration API requires no additional migration. Nightly schedules require `065_nightly_benchmarks.xml`.


## Benchmark batches and comparison

Enable **Run a batch**, choose repetitions per configuration, and add parameters to vary. Numeric parameters accept a comma-separated list or a From/To/Step range; boolean parameters accept `true, false`. Multiple varied parameters produce all combinations. The preview lists each configuration and the fixed settings before starting. Concurrency sweeps use the concurrent profile, including the one-stream case. Limits are 1,000 configurations and 10,000 total runs, independent of the sample count per run.

The server executes each configuration's repetitions before the next configuration.
One provider lease covers the whole batch, with progress and one cancel action.
The reservation follows the [same lifecycle](#automatic-lane-reservation) as a single run.
Closing the browser does not stop execution.
The first failed run stops the remaining batch; completed measurements stay stored.
Worker disconnects and orchestrator restarts stop the batch. Batches do not resume automatically.
Serving overrides remain applied, as for a single run.

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
Manual batches stop at the first failed run and do not retry automatically. Nightly runs use the separate retry and restoration policy linked above.

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

## Shared maintenance admission

Calibration runs first during its configured window (05:00–08:00 Europe/Berlin
by default). Benchmarks use the remaining time; new nightly configurations stop
at 07:50. Manual starts share the same PostgreSQL admission lock and durable
claims. At most one calibration or benchmark runs across all providers.
Conflicting manual starts return HTTP 409 rather than queueing.
Migration `065_nightly_benchmarks.xml` and workers with
`get_calibration_status` support are required. Calibration completion and
benchmark cleanup must finish before their claims are released.
`GET /internal/maintenance/status` lists the current holders, and
`POST /internal/maintenance/calibration/release` releases one calibration claim
after a normal stop on an administrator's request.
`POST /internal/maintenance/recovery/release {model_provider_id, force}` releases
a nightly recovery journal. Without `force` the worker must show the journal's
lane with its original `vllm_config`; otherwise it returns 409. It returns 404
when no recovery is pending and 409 while a recovery or one of its jobs runs.
See the [operator guide](../../docs/admin/nightly-benchmarks.md#calibration-priority-and-shared-execution).
