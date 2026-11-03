# DISCLAIMER: read this before you use any number from this study

**The point scores in `results/` were NOT judged blind. Do not quote them as blind results. Re-run and re-judge first.**

## 1. Point judgments saw the model names (both runs)

In both runs (2026-10-27 and 2026-11-02) the harness wrote the list of model
calls (`modelCalls`, with model ids such as `Qwen/Qwen3.8-27B` or
`bench-gpt-6.1-terra-medium`) into the run's `diagnostics`. The judge input
contains the diagnostics as `productArtifacts`. Claude Opus could therefore see
which model wrote the answer it scored.

Affected: every point value in `results/*.json` (`points.overall`, `abs`,
`diff`, `criteria`, `leaks`, and the old top-level `overall`, `abs`, `diff`,
`criteria`, `leaks` in the first-run file). The 82–83 / 86 / 89 points quoted
from the first run are affected too.

Fixed in this branch: the harness now returns model calls and agent runs under
a separate `telemetry` key that never reaches the judge
(`test_model_calls_are_telemetry_and_never_reach_the_judge`). New runs are blind.

## 2. The ranking context carried one candidate's artifacts

The ranking (`rank`) showed each judge six (rerun) or four (first run)
anonymous answers labelled A–F. The answers were blind. The shared situation
context, however, came from the Luna (C1) run and included its
`productArtifacts`: Luna's session title, Luna's suggestions and, through the
problem above, the model ids of Luna's calls. These could not be mapped to a
label directly, but they could hint at which answer Luna wrote.

Fixed in `rank.py`: the shared context no longer contains `productArtifacts`.

## 3. Other limits

- **Raw data of the first run is lost.** Only the aggregates in
  `results/first-run-2026-10-27.json` remain. The raw answers and judgments of
  the rerun are not in the repository; ask Patrick Bassner for the archive.
- **Gemma 4 timing (rerun):** the Morpheus cluster (CIT ITO) was overloaded in
  the night of 2026-11-02 (about 5 instead of about 50 tokens/s). The Gemma
  timing in `results/rerun-2026-11-02.json` comes from 14 requests between
  10:43 and 10:57 that morning, not from 25.
- **Costs:** `costPer1000PyrisPrices` uses the production price rows, which are
  OpenAI list prices converted to euro (factor 0.891), and ignores the prompt
  cache. Real bills differ: cached input costs 5–10 % of the input price,
  writing to the cache 125 %.
- **Rankings are not comparable across runs:** the first run ranked four
  answers (Sol, Luna, Gemma, Qwen), the rerun six.
- **Situations:** 39 own situations, not the corpus in `iris/qa/scenarios`.
  About 90 % of the weight is programming-exercise chat. Two repetitions, no
  human ratings.
- **Code:** both runs used the agent core of #1362 before it was merged, with
  this harness ported to it. The port is now part of this branch.
