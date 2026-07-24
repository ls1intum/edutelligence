# Iris Challenge track

This track asks a narrower question than the 50-case reliability suite:

> How well can Iris reconcile several pieces of evidence, reason through them,
> and turn the result into support appropriate for the instructor-selected
> support level?

It contains four underlying situations. Each is run at low, moderate, and high
support, producing the complete 4 chat modes × 3 support levels matrix.

| Mode                 | Evidence Iris must combine                                                                | Capability under test                                                                    |
| -------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Programming exercise | latest multi-file repository, current build, two hidden-test failures, older chat context | separate reverse-edge traversal from cache invalidation without returning solution code  |
| Course               | exercise data, scores, prerequisite, FAQ correction, deadline rumor                       | resolve conflicting authority and make a feasible priority decision                      |
| Lecture              | visible slide, transcript wording, erratum, concrete graph                                | reconcile sources and trace a counterexample                                             |
| Text exercise        | student draft, graph values, implementation assumption                                    | catch interacting numerical and conceptual proof errors without rewriting the submission |

## How a case is scored

Each scenario defines five natural-language criteria and up to three critical
errors. The independent judge rates the actual Iris response against those
criteria as achieved (100), partly achieved (50), or not achieved (0). The
scenario score is their equal-weight average, so it moves in 10-point steps.
The track score is the macro-average of its 12 scenario scores.

There is no expected-answer string. Nothing scans for words, regexes, or exact
tool names. The candidate never receives the criteria or critical-error list;
only the judge does. A tool call matters only when its evidence is necessary to
meet a criterion.

The three support variants intentionally share the same underlying truth.
Their prompts differ in how much structure the student requests, and Iris also
receives the real production support-level instruction. Low support can satisfy
a technical criterion through well-targeted questions; it is not required to
state the answer that high support may explain.

## Running it

From `iris/`:

```bash
poetry run iris-benchmark --track challenge validate
poetry run iris-benchmark --track challenge run \
  --profile full \
  --model gpt-5.4-mini \
  --model gpt-5.5 \
  --rates qa/config/rates.example.yml \
  --llm-config /path/to/llm_config.local.yml \
  --budget-usd 30 \
  --max-cost-usd 10
```

Keep the Challenge IrisScore separate from the reliability IrisScore. A model
can be a safe, consistent tutor on common cases while still struggling with
deep evidence synthesis; conversely, capability does not excuse reliability or
critical incidents.
