# Hard-scenario v2 experiment

## Purpose

The first corpus version verified product paths but left too many models at the
same ceiling. This experiment replaces five weak situations while keeping the
corpus at exactly 50. It tests whether ambiguity, conflicting evidence, and
necessary tool use create useful separation without encoding a preferred model
ordering.

The original corpus is preserved on
`iris/quality-assurance-simple-v1-checkpoint` at commit `b791ba7e4`.

## Five replacements

| Scenario                          | What makes it harder                                                                                                                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prog-batch-retry-high`           | Eight-file submission, three hidden failures, a plausible but stale concurrency hypothesis, two interacting state defects, and irrelevant retry/audit code |
| `tutor-batch-retry-investigation` | The same evidence must be compressed into three pedagogical suggestions without revealing the implementation                                               |
| `autonomous-extension-dispute`    | Current and archived rules, pending versus approved status, individual versus team scope, peer misinformation, and confidence calibration                  |
| `global-checkpoint-policy`        | Five sources with different dates and authority, including an archived rule and an unverified rumor                                                        |
| `text-ablation-ambiguity-low`     | Aggregate and subgroup disagreement, nonrandom assignment, changed measurement, selection, missing counts, and low-support tutoring constraints            |

## Harness defects found

Two product outputs were initially invisible to the evaluator:

1. Autonomous-tutor confidence was present in the callback but omitted from the
   evaluator evidence.
2. Tutor suggestion callbacks contain both a conversational `reply` and the
   tutor-facing `artifact`. The harness evaluated the reply whenever it existed
   and discarded the artifact. This particularly punished Sol because it
   followed the two-output contract consistently.

Both extraction paths now preserve the relevant product artifact. All tutor
scores produced before the artifact fix are invalid and excluded below.

## Valid one-run result

All GPT-5.6 reasoning-effort parameters were omitted so the provider selected
its defaults.

| Scenario                          | GPT-5.6 Sol | GPT-5.6 Luna |
| --------------------------------- | ----------: | -----------: |
| `prog-batch-retry-high`           |         100 |          100 |
| `tutor-batch-retry-investigation` |          80 |           50 |
| `autonomous-extension-dispute`    |          90 |           90 |
| `global-checkpoint-policy`        |         100 |          100 |
| `text-ablation-ambiguity-low`     |         100 |           90 |
| **Mean**                          |      **94** |       **86** |

There were no execution errors in these valid runs. Sol's main advantage came
from the tutor situation: it inspected the repository and covered both the
tenant-scoped identity problem and partial mutation before failure. Luna made
no tool call in its valid tutor run and omitted the tenant-scoping defect.

This is not yet a publishable ranking. Three of five situations remain at or
near ceiling, each model has only one valid run per situation, and the observed
difference is concentrated in one tool-selection decision. The experiment does
show that artifact-complete, multi-factor tutoring situations can distinguish
deployed Iris configurations once the correct product output is evaluated.

## Cost and next decision

All v2 development runs together used an estimated `$0.4179`, including the
tutor runs invalidated by the extraction defect. Rates are benchmark estimates,
not an Azure invoice.

Before expanding to all 50 situations, the next batch should reuse this design
pattern while avoiding obvious helper names and ground-truth clues. It should
add independent hard situations across programming, course, lecture, and text
chat, then repeat the difficult subset before interpreting small score gaps.
