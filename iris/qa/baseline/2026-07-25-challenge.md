# Iris Challenge baseline — 2026-07-25

This is the first live run of the 12-scenario Iris Challenge track. Every model
ran once against commit `e2922e23`, using the real Iris pipeline and the
independent GPT-5.4 judge. There were no execution errors. GPT-5.6 reasoning
effort and reasoning mode were omitted so the provider selected their defaults.

The result is a capability baseline, not a stability estimate. The intervals
below describe variation across the 12 scenarios; they do not measure
run-to-run variation.

## Results

| Model           | Challenge IrisScore | 95% interval | Critical-error rate | Execution errors | Measured cost |
| --------------- | ------------------: | -----------: | ------------------: | ---------------: | ------------: |
| `gpt-5.6-luna`  |           **93.33** | 84.86–100.00 |                0.0% |           0 / 12 |       $0.4978 |
| `gpt-5.6-sol`   |           **91.67** |  85.84–97.49 |                8.3% |           0 / 12 |       $1.2489 |
| `gpt-5.6-terra` |           **89.17** |  78.80–99.53 |                8.3% |           0 / 12 |       $0.7500 |
| `gpt-5.5`       |           **85.83** |  75.19–96.48 |               16.7% |           0 / 12 |       $1.2501 |
| `gpt-5.4-mini`  |           **79.17** |  66.76–91.58 |               25.0% |           0 / 12 |       $0.4774 |

The five complete runs cost **$4.2242** in measured model usage. A preceding
authenticated one-scenario probe cost $0.0307 and is not included in the table.

## Breakdown by chat mode

| Model           | Programming | Course | Lecture |  Text |
| --------------- | ----------: | -----: | ------: | ----: |
| `gpt-5.4-mini`  |       83.33 |  50.00 |   90.00 | 93.33 |
| `gpt-5.5`       |       93.33 |  66.67 |   90.00 | 93.33 |
| `gpt-5.6-sol`   |       96.67 |  86.67 |   90.00 | 93.33 |
| `gpt-5.6-terra` |       93.33 |  76.67 |   90.00 | 96.67 |
| `gpt-5.6-luna`  |      100.00 |  93.33 |   83.33 | 96.67 |

## What separated the models

The overall span is 14.16 points, compared with 3.33 points in the 50-scenario
reliability baseline. The challenge track therefore exposes model-dependent
behavior that the reliability suite compressed.

The course scenarios are the strongest discriminator. They require Iris to
notice conflicting dates and autonomously retrieve the authoritative FAQ:

- Luna retrieved the FAQ in all three support variants and had no critical
  incidents.
- Sol retrieved it in two variants and missed it in moderate support.
- Terra retrieved it in two variants and missed it in low support.
- GPT-5.5 retrieved it only in high support.
- Mini did not retrieve it in any variant.

Missing the FAQ caused the model to present the stale Thursday date as official,
which accounts for every model's deadline-related critical incident. This is an
agentic tool-selection result: the evaluator did not require a tool name, but
the answer could not reconcile the evidence without obtaining the FAQ content.

The low-support programming scenario also separates models (60–100). It rewards
finding both the reverse-edge traversal defect and graph-revision cache defect
while remaining Socratic. Moderate and high programming support are already
near ceiling.

Lecture and text scenarios add little ranking signal in their current form.
Lecture averages are almost identical and its low-support case is noisy; text
moderate/high and programming high are at ceiling. They remain useful checks,
but the next expansion should add independent, harder underlying situations
rather than more support variants of the same facts.

## Important limits

- This is one candidate run per scenario. The ranking is promising but not yet
  a stable leaderboard; the intervals overlap.
- The 12 scenarios are four underlying situations repeated across three support
  levels, so they are not 12 statistically independent tasks.
- The benchmark compares deployed Iris configurations, not isolated raw model
  intelligence. GPT-5.4-mini uses Iris's default chat variant while larger
  candidates use the advanced variant, and all candidates share auxiliary
  pipelines and the same judge.
- Pricing uses the checked-in reference rate card, which is not confirmed
  against the actual Azure invoice.

The next evidence-producing step is three or more repetitions plus a second
independent hard situation per chat mode. The reliability and challenge scores
should continue to be reported separately.
