# Iris Challenge replicated pilot — 2026-07-25

This is the first replicated live run of the 12-scenario Iris Challenge track.
It exercises the real Iris pipeline with an independent GPT-5.4 judge. The
benchmark implementation is commit `e2922e23`; later repetitions include only
the report commit `43b60533`. Production Iris code remained identical to
`origin/main` at `98069a3a`. GPT-5.6 reasoning effort and reasoning mode were
omitted so that every 5.6 deployment used its provider default.

The original single run suggested that Luna led Sol. Replication did not support
that conclusion. The three GPT-5.6 means are separated by only 0.56 points,
while Luna varied by 11.66 points from one complete run to another.

## Replicated results

The score is the arithmetic mean across all scenario trials for a model. The
range shows complete-run means, not a confidence interval. Critical incidents
remain a separate descriptive rate and do not alter IrisScore.

| Model           | Candidate runs | Mean IrisScore |   Run range | Critical-incident trials | Execution errors | Candidate cost |
| --------------- | -------------: | -------------: | ----------: | -----------------------: | ---------------: | -------------: |
| `gpt-5.4-mini`  |              2 |      **80.84** | 79.17–82.50 |           5 / 24 (20.8%) |           0 / 24 |        $0.9515 |
| `gpt-5.5`       |              2 |      **85.00** | 84.17–85.83 |           4 / 24 (16.7%) |           0 / 24 |        $2.4815 |
| `gpt-5.6-luna`  |              3 |      **88.61** | 81.67–93.33 |            3 / 36 (8.3%) |           0 / 36 |        $1.4919 |
| `gpt-5.6-terra` |              2 |      **88.75** | 88.33–89.17 |            2 / 24 (8.3%) |           0 / 24 |        $1.4901 |
| `gpt-5.6-sol`   |              3 |      **89.17** | 85.83–91.67 |           4 / 36 (11.1%) |           0 / 36 |        $3.7770 |

The measured candidate usage in this table was **$10.1920**. Two additional
judge-only passes cost $1.1323. A preceding authenticated probe cost $0.0307.
The project spend ledger ended at $28.3031 for the full development session,
including earlier suites and conservative failed-call reservations, below the
$30 session ceiling.

## What this result says

The supported descriptive ordering is:

`gpt-5.4-mini < gpt-5.5 < {gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol}`

This is not evidence that the three GPT-5.6 models are equally capable. It means
this pilot cannot resolve their ordering. Sol has the highest replicated mean,
as expected, but its advantage is only 0.42 points over Terra and 0.56 over
Luna—far smaller than run-to-run movement.

The expected ordering
`mini < Luna < 5.5 ≈ Terra < Sol` is therefore only partly supported:

- Mini is clearly lowest in this sample.
- Sol has the highest mean.
- Terra and Sol are effectively tied at this resolution.
- Luna did not fall below GPT-5.5; its mean landed in the unresolved GPT-5.6
  cluster, with substantially more variance than the other deployments.

No result was moved or thresholded to fit an expected model hierarchy.

## Candidate variation

| Model           | Run 1 | Run 2 | Run 3 | Full-run span |
| --------------- | ----: | ----: | ----: | ------------: |
| `gpt-5.4-mini`  | 79.17 | 82.50 |     — |          3.33 |
| `gpt-5.5`       | 85.83 | 84.17 |     — |          1.66 |
| `gpt-5.6-luna`  | 93.33 | 90.83 | 81.67 |         11.66 |
| `gpt-5.6-terra` | 89.17 | 88.33 |     — |          0.84 |
| `gpt-5.6-sol`   | 91.67 | 85.83 | 90.00 |          5.84 |

Luna's third run is the clearest warning against a one-run leaderboard. Its
course scores changed from 70/80/100 in run 2 to 20/30/100 in run 3 despite
identical scenarios and configuration. Sol also moved materially, especially
in low-support lecture behavior. These are changes in agentic retrieval and
tool-selection behavior, not deployment-name swaps: every saved output records
the intended model ID.

## Breakdown by chat mode

These values aggregate every candidate repetition.

| Model           | Programming | Course | Lecture |  Text |
| --------------- | ----------: | -----: | ------: | ----: |
| `gpt-5.4-mini`  |       90.00 |  53.33 |   88.33 | 91.67 |
| `gpt-5.5`       |       96.67 |  68.33 |   83.33 | 91.67 |
| `gpt-5.6-luna`  |       97.78 |  75.56 |   84.44 | 96.67 |
| `gpt-5.6-terra` |       95.00 |  80.00 |   86.67 | 93.33 |
| `gpt-5.6-sol`   |       95.56 |  83.33 |   80.00 | 97.78 |

Course chat remains the strongest discriminator. It requires Iris to reconcile
conflicting dates by retrieving the authoritative FAQ. Programming and text are
near ceiling for the larger models, so they contribute little information about
relative model capability. Lecture behavior is noisy and does not follow model
size consistently.

## Breakdown by instructor support level

| Model           |   Low | Moderate |  High |
| --------------- | ----: | -------: | ----: |
| `gpt-5.4-mini`  | 73.75 |    81.25 | 87.50 |
| `gpt-5.5`       | 68.75 |    92.50 | 93.75 |
| `gpt-5.6-luna`  | 75.00 |    91.67 | 99.17 |
| `gpt-5.6-terra` | 76.25 |    93.75 | 96.25 |
| `gpt-5.6-sol`   | 80.83 |    90.00 | 96.67 |

High-support cases are close to saturation. Most separation and most variance
come from low support, where the model must both investigate autonomously and
avoid taking over the student's work.

## Judge stability check

The original Sol and Luna answers were judged three times. Candidate models
were not invoked for the second and third passes.

| Fixed candidate answers | Judge pass 1 | Judge pass 2 | Judge pass 3 | Pass span |
| ----------------------- | -----------: | -----------: | -----------: | --------: |
| `gpt-5.6-sol`           |        91.67 |        90.00 |        90.83 |      1.67 |
| `gpt-5.6-luna`          |        93.33 |        91.67 |        92.50 |      1.66 |

Relative to pass 1:

- Pass 2 agreed on 91.7% of criterion ratings, with a 3.33-point mean absolute
  difference per scenario.
- Pass 3 agreed on 95.0% of criterion ratings, with a 2.50-point mean absolute
  difference per scenario.
- Both passes agreed on 100% of individual critical-incident flags.

The judge contributes measurable noise, but materially less than Luna's and
Sol's candidate-run variation. It preserved the Luna-over-Sol ordering of those
particular fixed answers in all three passes; replication showed that ordering
does not generalize to fresh candidate runs.

## Important limits and next step

- The 12 scenarios contain four underlying situations repeated across three
  support levels. They are not 12 independent capability tasks.
- Replication is asymmetric because it was performed under a fixed spend cap:
  Mini, GPT-5.5, and Terra have two runs; Luna and Sol have three.
- The benchmark compares deployed Iris configurations, not isolated raw model
  intelligence. Candidates share auxiliary pipelines and the same judge.
- Pricing uses the checked-in reference rate card and is not confirmed against
  the Azure invoice.

The next useful investment is not more repetitions of these four situations.
It is additional independent, difficult situations with multi-file evidence,
longer histories, and consequential tool choices. Once those exist, every model
should receive the same number of candidate repetitions before publishing a
ranked leaderboard.
