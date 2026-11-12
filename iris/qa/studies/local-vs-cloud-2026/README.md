# Study: local open models vs. cloud models in Iris (2026)

> **⚠️ READ [DISCLAIMER.md](DISCLAIMER.md) FIRST.** The point scores in
> `results/` were **not judged blind**: the judge input contained the model
> names. The harness bug is fixed in this branch, but the stored numbers are
> affected. Re-run and re-judge before you use them.

This folder holds the scripts, the 39 situations and the aggregated results of
a study that compared local open models with cloud models in the Iris chat. It
answered two questions: how close are local models to the cloud models, and
how does GPT-6.1 Terra compare to Luna and Sol before it became the production
chat model. It uses the production pipeline through the benchmark harness in
`iris/src/iris/qa` and changes only the model under test.

## Models (labels)

| Label | Model                                     | Where                          |
| ----- | ----------------------------------------- | ------------------------------ |
| C1    | GPT-6 Luna, medium (production default)   | Cloud via Logos                |
| C2    | GPT-6.1 Sol, medium (production advanced) | Cloud via Logos                |
| C3    | GPT-6.1 Terra, medium                     | Cloud via Logos                |
| L1    | Qwen3.8-27B (production local)            | Logos, RTX PRO 6000 Blackwell  |
| L2    | gpt-oss-120b, medium                      | Logos                          |
| L3    | Gemma 4 31B, thinking off                 | Morpheus (CIT ITO), A100       |
| L4    | Gemma 4 31B, thinking on                  | Morpheus (CIT ITO), A100       |
| A1/A2 | Claude Opus / Sonnet 5.5 as the tutor     | Anthropic API (first run only) |

Side tasks (titles, suggestions, review step) keep their production models in
every configuration. Gemma 4 has no thinking levels, only on and off; check the
output tokens per model before you trust a run.

## Results at a glance

Rerun of 2026-11-02 (`results/rerun-2026-11-02.json`, 39 situations × 2):

| Model   | Points\* | Mean rank, Opus | Mean rank, Gemini | Answer time (median) | Cost per 1,000 answers\*\* |
| ------- | -------: | --------------: | ----------------: | -------------------: | -------------------------: |
| Sol     |       89 |             1.8 |               1.8 |                8.8 s |                     28.7 € |
| Terra   |       88 |             2.4 |               2.6 |                7.6 s |                     14.6 € |
| Luna    |       85 |             2.7 |               3.1 |                8.4 s |                      1.6 € |
| Qwen3.8 |       83 |             3.6 |               3.6 |               19.6 s |                          – |
| Gemma 4 |       82 |             4.3 |               3.9 |             20.4 s\* |                          – |
| gpt-oss |       64 |             5.2 |               5.4 |                5.4 s |                          – |

\* Not blind, see the disclaimer. Gemma's time comes from 14 requests only.
\*\* Production price rows without prompt cache.

The first run of 2026-10-27 (`results/first-run-2026-10-27.json`) ranked four
answers (Sol, Luna, Gemma, Qwen) and also holds the Gemma 4 26B A4B add-on test
(`moe`). Its raw data is lost.

## Files

| Path               | Purpose                                                               |
| ------------------ | --------------------------------------------------------------------- |
| `scenarios/`       | The 39 situations in harness format, with `manifest.json` (hashes)    |
| `results/`         | Aggregated results of both runs                                       |
| `build_configs.py` | Builds one Iris configuration per model from copies of the prod files |
| `run_matrix.py`    | Runs all situations × configurations × repetitions                    |
| `run_one.py`       | Runs one situation in its own process                                 |
| `run_latency.py`   | Clean timing run, one request at a time per model                     |
| `judge_points.py`  | Point judging with Claude Opus (`claude -p`)                          |
| `rank.py`          | Blind ranking of all answers per situation (Opus or Gemini Argon)     |
| `analyze.py`       | Writes the result JSON (points, ranking, timing, cost)                |
| `study_paths.py`   | Shared paths and environment variables                                |

## How to run it

All commands run from `iris/` with the Poetry environment, for example
`poetry run python qa/studies/local-vs-cloud-2026/run_matrix.py ...`.

1. **Configuration.** Copy the production `application.yml` and
   `llm_config.yml` to a private folder as `application.prod.yml` and
   `llm_config.prod.yml`. Put your own Logos key in `logos.key` in another
   private folder. Never use the production keys. Then run
   `build_configs.py PRODCFG_DIR KEYS_DIR OUT_DIR` and set
   `IRIS_STUDY_CONFIG=OUT_DIR`. OUT_DIR contains keys: keep it outside the
   repository.
2. **Data folder.** Set `IRIS_STUDY_DATA` to a permanent, backed-up folder
   (default: `./data`, ignored by git). Never use `/tmp`: it is deleted.
3. **Quality run.** `run_matrix.py runs 2 C1 C2 C3 L1 L2 L4`. Product failures
   (for example a broken tool call) are kept as findings and not retried;
   infrastructure errors are retried.
4. **Timing run.** Only when no quality run is active:
   `run_latency.py timing C1 C2 C3 L1 L2 L4`. Check Morpheus speed first.
5. **Judging.**
   `judge_points.py points --select runs:C1:1+2,runs:C2:1+2,...` and
   `rank.py opus 12 runs ranking-opus C2 C3 C1 L4 L1 L2`, plus the same with
   `argon` and `GEMINI_API_KEY` set. Opus via `claude -p` stops at the 5-hour
   subscription limit; restart the command later, it resumes.
6. **Summary.** `analyze.py results.json --labels C2 C3 C1 L4 L1 L2`.

Costs of the rerun for comparison: about 1.31 USD via Logos for Luna, Sol and
Terra, and about 2.91 USD for the Gemini rankings.

## Lessons from the runs

- Check the thinking setting of every model before a run (Gemma 4 thinks only
  when `enable_thinking` is set).
- Do not run timing and quality runs at the same time.
- Judges favour their own model family (GPT-6.1 Sol as judge preferred GPT
  answers by about 6 points). Grok 4.7 rated almost everything 91–92 and was
  dropped. Use judges from vendors outside the candidates where possible.
- Morpheus speed changes a lot during the day; probe it before timing.
