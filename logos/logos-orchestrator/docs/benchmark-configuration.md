# Configurable model benchmarks

The Models → Performance runner supports public Hugging Face datasets with a plain-text prompt column. Search selects a repository; configuration, split and prompt column are loaded from the HF Dataset Viewer. Private/gated datasets and structured conversation or multimodal columns are not supported by this editor.

## Data loading

The default remains `openai/gsm8k`, configuration `main`, split `test`, prompt column `question`. Search and schema discovery query Hugging Face metadata APIs; the browser does not download the dataset. When the job starts, GuideLLM 0.7.2 uses `datasets.load_dataset` on the orchestrator. This downloads/prepares data and reuses the Hugging Face cache on subsequent runs while that cache exists. The dataset is not bundled in the Logos image. Cache survival across container replacement depends on deployment storage; the code does not guarantee it. A small sample count limits benchmark requests, not necessarily the volume downloaded by the datasets library.

These are serving-performance benchmarks. Choosing GSM8K supplies its questions as prompts; Logos does not grade answers against the dataset's reference answers.

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
