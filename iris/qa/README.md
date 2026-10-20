# Iris benchmark

This directory contains one inspectable corpus of exactly 50 synthetic Iris
situations. Each situation is an ordinary Artemis request with the fixture data
and programming repositories needed to run it through the real production
pipeline. The benchmark does not change Iris.

The complete row-by-row inventory is in [CORPUS.md](CORPUS.md).

## The corpus

The corpus deliberately counts situations, not prompt variants. A student
problem appears once at one instructor support level; low, moderate, and high
support are balanced across different problems instead of triplicating the same
facts.

| Chat mode                 | Low | Moderate | High | Total |
| ------------------------- | --: | -------: | ---: | ----: |
| Programming exercise chat |   4 |        4 |    4 |    12 |
| Course chat               |   4 |        3 |    3 |    10 |
| Lecture chat              |   3 |        4 |    3 |    10 |
| Text exercise chat        |   3 |        3 |    4 |    10 |
| **All chat situations**   |  14 |       14 |   14 |    42 |

The remaining eight situations cover three tutor suggestions, three autonomous
tutor decisions, and two global searches. This keeps every production use case
in one corpus without growing the benchmark into hundreds of cases.

The `difficulty` field separates 28 foundation situations from 22 advanced
situations. Advanced situations require several connected decisions: reconciling
conflicting sources, tracing counterexamples, interpreting submission history,
or diagnosing independent defects. They use five plain-language criteria;
foundation situations use three.

Examples of advanced evidence include:

- multi-file repositories, submission histories, build logs, and independent
  hidden failure families, including type inference, stream recovery, and
  incremental evaluation;
- stale course displays, official FAQ corrections, personal rules,
  prerequisites, and unsupported rumors;
- visible slides, transcript slips, later errata, and numerical or execution
  traces; and
- student drafts containing interacting proof, causal, statistical, privacy,
  or source-attribution errors.

## Scoring

An independent judge sees the scenario goal, the candidate answer, the
production activity trace, and bounded fixture evidence. Chat situations are
rated on the same five criteria, explained in [RUBRIC.md](RUBRIC.md), with
`reference` entries that tell the judge what is true in the situation. The other
use cases bring their own criteria. The judge rates each criterion as:

| Rating            | Points |
| ----------------- | -----: |
| `achieved`        |    100 |
| `partly_achieved` |     50 |
| `not_achieved`    |      0 |

IrisScore is the equal-weight average of the 50 scenario scores. Every
situation counts once, even when an advanced situation has more criteria.
Reports also show chat-mode, support-level, use-case, and difficulty breakdowns.
Critical incidents and execution failures stay separate from IrisScore. For
chat situations the report also shows the share of usable answers, a
usage-weighted score, and the mean points per criterion.

There is no expected-answer string, keyword scan, regular expression, required
tool name, or pass/fail threshold. A tool call matters only when the resulting
evidence is needed to satisfy a criterion.

Repeated executions do not create more corpus entries or additional weight.
When `--repetitions` is greater than one, the runner first averages repetitions
within each named situation. The resulting range measures consistency of the
deployed Iris configuration separately from average quality.

## Run locally

From `iris/`:

```bash
poetry install
poetry run iris-benchmark validate
poetry run iris-benchmark list --profile full
poetry run iris-benchmark list --difficulty advanced
poetry run iris-benchmark plan \
  --rates qa/config/rates.example.yml \
  --budget-usd 30
poetry run iris-benchmark run \
  --llm-config /path/to/llm_config.local.yml \
  --rates qa/config/rates.example.yml \
  --budget-usd 30 \
  --max-cost-usd 30 \
  --output qa-results/my-run
```

Pass `--model` once or more to select candidates such as
`openai/gpt-oss-120b`, `gpt-6.1-sol`, or `gpt-6-luna`. Omitting `--model`
selects every candidate in the rate card, including the reasoning-effort
variants below, so pass `--model` for a focused comparison.

To compare reasoning efforts of one model, run its variants side by side, for
example:

```bash
poetry run iris-benchmark run \
  --llm-config /path/to/llm_config.local.yml \
  --rates qa/config/rates.local.yml \
  --budget-usd 30 \
  --max-cost-usd 30 \
  --repetitions 3 \
  --model gpt-6-luna-medium --model gpt-6-luna-high \
  --model gpt-6.1-sol-medium --model gpt-6.1-sol \
  --output qa-results/effort-comparison
```

### Collect now, judge later

The built-in judge needs Azure credentials. To run without it, collect the
candidate answers first and let a judge outside the harness rate them. With
`--skip-judge`, `plan`, `doctor` and `run` leave the judge out of the cost and
configuration, and an `llm_config` that contains only Logos entries is enough:
the candidate and the helper model that Iris itself calls are both served by
Logos.

```bash
poetry run iris-benchmark run \
  --skip-judge \
  --llm-config /path/to/llm_config.local.yml \
  --rates qa/config/rates.local.yml \
  --budget-usd 30 --max-cost-usd 30 \
  --model gpt-6-luna-medium --model gpt-6.1-sol-medium \
  --output qa-results/collected

poetry run iris-benchmark judge-export \
  --input-run qa-results/collected \
  --output qa-results/judge
```

`judge-export` writes one bundle per answered trial to `qa-results/judge/bundles`.
A bundle holds the judge system prompt and the exact request the built-in judge
would receive. Its id (`t001`, `t002`, ...) carries no model or repetition
information, and the order is shuffled, so the judge cannot tell which model
wrote an answer. `qa-results/judge/key.json` maps the ids back to trials; the
judge must not read it.

The judge writes one file per bundle, `<judgments>/<id>.json`, in the shape the
built-in judge returns:

```json
{
  "criteria": [
    { "id": "trustworthy", "rating": "achieved", "evidence": "..." }
  ],
  "criticalErrors": [
    { "description": "<exact text>", "present": false, "evidence": "..." }
  ]
}
```

Then import them:

```bash
poetry run iris-benchmark judge-import \
  --input-run qa-results/collected \
  --judgments qa-results/judgments \
  --key qa-results/judge/key.json \
  --judge-label "<judge model and settings>" \
  --output qa-results/scored
```

The import checks every judgment (exact criterion ids, valid ratings, one result
per critical error) and lists missing or invalid ones before it writes the usual
report. The report records the judge label; the cost column covers the
candidate and helper calls only.

To reuse paid candidate answers after changing only evaluator context:

```bash
poetry run iris-benchmark rejudge \
  --input-run qa-results/my-run \
  --llm-config /path/to/llm_config.local.yml \
  --rates qa/config/rates.example.yml \
  --budget-usd 30 \
  --max-cost-usd 5 \
  --output qa-results/my-rejudged-run
```

The local LLM file is read only to create short-lived worker configuration
files. It is never copied into a report or committed. Azure chat entries supply
the Azure candidates, helpers, and evaluator. `openai_chat` entries at
`https://logos.aet.cit.tum.de/v1` supply the Logos candidates. Their API key is
written only to the short-lived worker file and is never included in report
metadata. The rate card is a cost guard; verify its values against actual
billing before a paid run. For GPT-5.6 and GPT-OSS candidates, the harness
omits reasoning effort and reasoning mode so the provider selects its defaults.
The GPT-6 Logos candidates use the Responses API and fixed comparison settings.
Each candidate id sends one model with one reasoning effort:

| Candidate            | Logos model   | Reasoning effort |
| -------------------- | ------------- | ---------------- |
| `gpt-6.1-sol`        | `gpt-6.1-sol` | `high`           |
| `gpt-6.1-sol-medium` | `gpt-6.1-sol` | `medium`         |
| `gpt-6-luna`         | `gpt-6-luna`  | `xhigh`          |
| `gpt-6-luna-high`    | `gpt-6-luna`  | `high`           |
| `gpt-6-luna-medium`  | `gpt-6-luna`  | `medium`         |

The variants share the Logos model entry of the local LLM file, so no extra
configuration is needed. They have their own rate-card rows so that their cost
is reported separately; the example rows are zero like the other Logos
candidates, so put real prices into `rates.local.yml` to compare cost.

Before a worker starts, the runner records that trial's full cost bound. It
replaces the bound with actual usage only after the candidate and evaluator
both return complete token counts. A timeout or incomplete result keeps the
full bound. The worker also applies each situation's agent-turn, per-call
output, and total token limits before it sends another model request.

The CLI exits non-zero for invalid fixtures, budget refusal, or execution/judge
errors. A low score is benchmark data, not a command failure.

## Layout

- `scenarios/` — the complete 50-situation corpus.
- `RUBRIC.md` — the five criteria every chat answer is rated on.
- `fixtures/` — deterministic course, retrieval, lecture, memory, draft, and
  prompt context.
- `artifacts/` — student repositories, reference repositories, tests, build
  evidence, and chronological submission histories.
- `config/rates.example.yml` — visible pricing assumptions for the cost guard.
- `baseline/` — the initial full-corpus snapshot and the replicated six-model
  hard-scenario comparison. These are historical results tied to the source
  revisions named in each report. The latter is documented in
  `baseline/2026-08-02-hard-v5-gpt56.md`; a fresh current-main run is required
  before treating either report as today's baseline.

Raw candidate answers stay under the local run directory. Published Markdown
and JSON reports omit raw answers and credentials.
