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
production activity trace, and bounded fixture evidence. It rates each natural
language criterion as:

| Rating            | Points |
| ----------------- | -----: |
| `achieved`        |    100 |
| `partly_achieved` |     50 |
| `not_achieved`    |      0 |

IrisScore is the equal-weight average of the 50 scenario scores. Every
situation counts once, even when an advanced situation has more criteria.
Reports also show chat-mode, support-level, use-case, and difficulty breakdowns.
Critical incidents and execution failures stay separate from IrisScore.

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

Pass `--model openai/gpt-oss-120b` to run only the Logos candidate. Omitting
`--model` selects every candidate in the rate card.

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
the OpenAI candidates, helpers, and evaluator. An `openai_chat` entry for
`openai/gpt-oss-120b` at `https://logos.aet.cit.tum.de/v1` supplies the optional
Logos candidate. Its API key is written only to the short-lived worker file and
is never included in report metadata. The rate card is a cost guard; verify its
values against actual billing before a paid run. For GPT-5.6 and GPT-OSS
candidates, the harness omits reasoning effort and reasoning mode so the
provider selects its defaults.

The CLI exits non-zero for invalid fixtures, budget refusal, or execution/judge
errors. A low score is benchmark data, not a command failure.

## Layout

- `scenarios/` — the complete 50-situation corpus.
- `fixtures/` — deterministic course, retrieval, lecture, memory, draft, and
  prompt context.
- `artifacts/` — student repositories, reference repositories, tests, build
  evidence, and chronological submission histories.
- `config/rates.example.yml` — visible pricing assumptions for the cost guard.
- `baseline/` — historical reports. Reports created before this consolidation
  describe the former reliability/challenge split and are not directly
  comparable to a new 50-situation run. The replicated six-model hard-scenario
  comparison is documented in `baseline/2026-08-02-hard-v5-gpt56.md`.

Raw candidate answers stay under the local run directory. Published Markdown
and JSON reports omit raw answers and credentials.
