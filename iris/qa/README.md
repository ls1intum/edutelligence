# Iris benchmark

This directory is a small, repeatable benchmark for the current Iris code. It
does not change Iris. Each scenario is an ordinary synthetic Artemis request,
with the fixture data and programming repositories needed to run it through the
real production pipeline.

## What is measured

Every scenario contains three plain-language `criteria` and, when useful, a
short list of `critical_errors`. An independent judge sees the scenario goal,
the candidate's answer, the production activity trace, and bounded fixture
evidence. It rates each criterion as:

| Rating            | Points |
| ----------------- | -----: |
| `achieved`        |    100 |
| `partly_achieved` |     50 |
| `not_achieved`    |      0 |

The model's **IrisScore** is the equal-weight average of scenario scores. A
scenario counts once regardless of how many criteria it has, and a model's
score is the macro-average across scenarios. Critical-error rate and execution
errors are shown separately so a good average cannot hide a dangerous incident.
There is intentionally no arbitrary pass/fail threshold in this benchmark.

With `--repetitions 3` or more, repeated trials are averaged per scenario
before the model score is calculated. Reports include a 95% interval over the
resulting scenario scores. A single run is a baseline, not a stability claim.

## Run locally

From `iris/`:

```bash
poetry install
poetry run iris-benchmark validate
poetry run iris-benchmark list --profile full
poetry run iris-benchmark plan \
  --rates qa/config/rates.example.yml \
  --budget-usd 30
poetry run iris-benchmark run \
  --llm-config /path/to/llm_config.local.yml \
  --rates qa/config/rates.example.yml \
  --budget-usd 30 \
  --max-cost-usd 30 \
  --output qa-results/my-baseline
```

The local LLM file is read only to create short-lived worker configuration
files. It is never copied into a report or committed. The rate card is a cost
guard; verify its values against the Azure billing for the deployments you use.
For the GPT-5.6 candidates, the harness deliberately omits reasoning effort and
reasoning mode so the provider selects its defaults. OpenAI currently documents
those defaults as medium effort in standard mode:
<https://developers.openai.com/api/docs/guides/reasoning#reasoning-mode>.

The CLI exits non-zero for invalid fixtures, budget refusal, or execution/judge
errors. A low IrisScore is data, not a command failure.

## Corpus layout

- `scenarios/` — 50 requests covering all four chat modes at low, moderate, and
  high support, plus tutor suggestions, autonomous tutoring, and global search.
- `fixtures/` — deterministic retrieval, memory, metrics, deadline, and prompt
  context data.
- `artifacts/` — realistic student repositories, submission histories, tests,
  compiler logs, drafts, and reference solutions.
- `config/rates.example.yml` — editable, visible pricing inputs for the guard.

Raw answers stay under the local run directory for diagnosis. The published
Markdown and JSON reports omit raw candidate answers and credentials.
