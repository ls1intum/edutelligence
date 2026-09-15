# Configurable model benchmarks

The Models → Performance runner supports public Hugging Face datasets with a plain-text prompt column. Search selects a repository; configuration, split and prompt column are loaded from the HF Dataset Viewer. Private/gated datasets and structured conversation or multimodal columns are not supported by this editor.

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

vLLM overrides apply only to Logos workers. Blank fields keep the current worker value; explicit false is preserved. The orchestrator prepares an idle lane, prevents routing during reconfiguration, merges the selected overrides, and asks the worker to reload. The worker checks its active-request counters under the lane lock before restarting. The orchestrator waits for the updated configuration to appear in worker status before measuring. Unsupported settings, worker errors and timeouts fail the job instead of recording a successful run.

Changed vLLM settings remain active after the benchmark, including if measurement fails or is cancelled after reconfiguration. There is no automatic rollback. Deploy the updated workernode together with the orchestrator to enforce the `require_idle` reconfiguration guard.

## API

All Spring endpoints below require `logos_admin` and forward to the internal orchestrator API using the existing internal authentication:

- `POST /logosdb/model_benchmarks/datasets/search`: `{ "query": "gsm8k" }`
- `POST /logosdb/model_benchmarks/datasets/metadata`: `{ "dataset": "openai/gsm8k", "subset": "main", "split": "test" }` (subset and split are optional)
- `POST /logosdb/model_benchmarks/run`: existing target and sample fields plus `dataset`, `subset`, `split`, `text_column`, `profile`, `concurrency`, `seed` and optional `serving_overrides`.

The selected settings are persisted with the job; successful results store the actual GuideLLM scenario and the worker's serving snapshot. No database migration is required.


## Benchmark batches and comparison

Enable **Run a batch**, choose repetitions per configuration, and add parameters to vary. Numeric parameters accept a comma-separated list or a From/To/Step range; boolean parameters accept `true, false`. Multiple varied parameters produce all combinations. The preview lists each configuration and the fixed settings before starting. Concurrency sweeps use the concurrent profile, including the one-stream case. Limits are 1,000 configurations and 10,000 total runs, independent of the sample count per run.

The start confirmation appears above the button. Confirming once submits the complete plan to the server; closing the browser does not stop execution. Each configuration is repeated before advancing to the next one. One provider lease covers the whole batch, with progress and one cancel action. The first failed run stops the remaining batch; completed measurements stay stored. Worker disconnects and orchestrator restarts stop the batch under the existing lease rules; batches do not resume automatically after a server restart. Serving overrides remain applied, as for a single run.

The existing run endpoint accepts optional `batch: { configurations: [...], repetitions: 3 }`. Every configuration contains the same settings as a single run, using `samples` (1–100) inside the batch. Configurations are complete settings, not patches to the outer request. All configurations and their hardware limits are validated before a job is created. Every changed serving key must be present in every configuration to avoid inheriting a prior run's value. The job result exposes `total_runs`, `run_index` (one-based), `completed_runs`, `configuration_index`, and `repetition`.

The two comparison charts sit side by side on desktop and stack on narrow screens. Each box summarizes run-level measurements for one parameter value, with all other recorded controls matching the reference. Quartiles use linear interpolation; whiskers reach the last observations within 1.5 times the interquartile range. Dots show outliers, `n` counts captured measurements, and a single measurement appears as a line. These are distributions across runs, not pooled request latencies. The individual-run table is collapsed and loads 50 rows at a time.
