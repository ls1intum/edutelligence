# Iris Quality Assurance Architecture

## Objective

Build a repeatable, cost-bounded evaluation suite that executes the production
Iris chat pipeline against real Azure OpenAI deployments and measures whether
the answer, tool activity, grounding, pedagogical direction, and support-level
behavior remain acceptable. The suite must detect both absolute quality
failures and regressions without depending on exact response text.

The initial qualification targets are `gpt-5.4-mini` and `gpt-5.5`. The hard
cumulative budget for development qualification runs is USD 30. The runner
must stop before exceeding it; a larger budget requires explicit approval.

## Source-derived scope

The current production path has four chat modes:

- `COURSE_CHAT`
- `LECTURE_CHAT`
- `PROGRAMMING_EXERCISE_CHAT`
- `TEXT_EXERCISE_CHAT`

Every mode supports `low`, `moderate`, and `high` instructional support. The
unified chat pipeline's `default` and `advanced` variants differ only through
model binding; they do not select different prompt or tool behavior. The QA
matrix therefore treats the two requested candidate model profiles as the
third axis and covers all 24 mode/support/model combinations, plus the
orthogonal behaviors that materially change execution:

- programming submission details, build logs, feedback, repository listing,
  and file lookup;
- proactive `build_failed` and `progress_stalled` events;
- lecture retrieval, current slide/video/combined-view context, and citations;
- FAQ retrieval and citations;
- course exercises, competencies, metrics, and class comparisons;
- Memiris retrieval;
- MCQ widget generation;
- session titles and course/programming interaction suggestions;
- English and German behavior;
- custom-instruction and retrieved-content prompt injection;
- missing or insufficient context;
- academic-integrity and sensitive-data boundaries.

Three additional student/tutor-facing use cases have their own production
pipelines and must be evaluated too:

- communication tutor suggestions, including initial suggestions, copyable
  replies, and regeneration from a previous artifact;
- autonomous tutor decisions, including `NO_RESPONSE_NEEDED`, grounded replies,
  discussion awareness, confidence formatting, and prompt-injection resistance;
- global-search answers, including grounded source selection, no-source
  suppression, and the navigation-query path that deliberately skips answer
  generation.

Content ingestion, rewriting, inconsistency checking, and competency extraction
remain covered by deterministic pipeline tests. They do not produce a next chat
answer and are therefore outside the conversational scenario suite.

## Execution architecture

The runner will execute the real `ChatPipeline`, real prompt templates, real
tool factories, real agent loop, programming guide pass, citation pipeline,
MCQ pipeline, title pipeline, and suggestion pipeline. Scenario-owned adapters
replace only external systems:

- Weaviate retrieval returns fixture lecture and FAQ records.
- Artemis status callbacks are recorded locally rather than posted.
- Memiris reads fixture memories and suppresses background writes.
- Azure OpenAI calls remain real.

The adapter layer will be applied in a narrow context around one scenario and
will have contract tests against production constructor and call signatures.
The production pipeline should not gain scenario-specific conditionals.

The CLI bootstraps both `APPLICATION_YML_PATH` and `LLM_CONFIG_PATH` before the
first Iris import and resets singleton state between isolated test processes.
It constructs a production-like model profile for each candidate:

- `gpt-5.4-mini`: candidate chat and programming guide use `gpt-5.4-mini`;
- `gpt-5.5`: candidate chat uses `gpt-5.5`, while the programming guide remains
  fixed to `gpt-5.4-mini`, matching the current advanced-profile architecture;
- title, suggestion, citation, MCQ, and retrieval-adjacent auxiliary roles stay
  fixed to `gpt-5.4-mini` for both profiles.
- tutor-suggestion and autonomous-tutor `chat` roles use the selected candidate;
  global-search `answer` uses the candidate while its HyDE query generator stays
  fixed to `gpt-5.4-mini`.

Programming results separately record the raw candidate draft, guide rewrite
decision, guide rewrite rate, and delivered answer. Final-answer quality
measures the product profile; raw-draft diagnostics preserve sensitivity to the
candidate model.

Scenario retrieval adapters stub the output of `LectureRetrieval` and
`FaqRetrieval`. They deliberately test whether chat selects and grounds itself
in controlled retrieved evidence, not whether query rewriting, embeddings,
Weaviate search, or Cohere reranking retrieve the right evidence. Retrieval
quality is outside this suite and no embedding or reranker network calls occur.

Azure API-key authentication remains available for local qualification. Entra
authentication is explicit implementation scope: make API-key and bearer-token
provider auth mutually exclusive, add `azure-identity`, and support refreshing
bearer tokens in both Azure Chat Completions and Responses API clients.
Before candidate spend, an Azure Resource Manager listing must prove the
selected candidate deployment plus the `gpt-5.4-mini` auxiliary and independent
`gpt-5.4` judge deployments. A default two-candidate run therefore proves all
three configured names. The inference-only `Cognitive Services OpenAI User`
role can read this metadata without gaining deployment mutation or key access.
The runner requires a matching proof no older than one hour and preserves model
versions in the report.

## Scenario format

Each YAML scenario contains:

- stable ID, description, tags, risk level, mode, support level,
  language, and weekly/full profile membership;
- complete chat history and the next student turn;
- an optional proactive event carried out of band from the DTO, matching the
  router's `?event=build_failed` / `?event=progress_stalled` query parameter;
- course, exercise, lecture, current-view, metrics, FAQ, memory, and submission
  fixture references;
- required, optional, forbidden, and ordered tool activities;
- deterministic expectations such as language, maximum size, question-only
  behavior, citations, MCQ payloads, forbidden disclosures, and required
  concepts, plus the expected session-title and interaction-suggestion side
  artifacts;
- a weighted semantic rubric with critical criteria and scenario-specific
  evidence supplied to the judge;
- an estimated token ceiling.

Tutor-suggestion and autonomous-tutor records also carry low, moderate, and
high support settings exactly as Artemis sends them. Their current Iris prompt
paths do not branch on support level, so the suite covers the wire combinations
without inventing behavioral differences that production does not implement.

Programming fixtures contain full template, solution, test, and student
repository snapshots plus a chronological submission/commit history. The
history is provenance and satisfies repeatable artifact reconstruction; the QA
wire payload intentionally passes only the selected latest submission. The
submission history and uncommitted working tree are not sent by Artemis today;
scenarios test that Iris does not claim visibility into them. Fixtures are authored
as Artemis-shaped JSON with omitted empty fields and are parsed through the real
Pydantic DTOs. Contract tests enforce casing, camelCase aliases, polymorphic
message contents (including raw-JSON MCQ history and the declared image wire
shape), unique persisted IDs, chronological timestamp encoding,
language-specific repository filtering, unfiltered test repositories, and
round-trip parity with one representative Artemis payload per mode. Artemis's
current `PyrisMessageDTO.of` path emits text and JSON history; image parsing is
kept as a DTO drift contract rather than a paid scenario.

## Initial 50-scenario matrix

The 42 unified-chat scenarios have deliberately balanced support-level totals:
14 low, 14 moderate, and 14 high. Every scenario, including the eight separate
use-case scenarios, is executed against both model profiles unless the source
path intentionally skips an LLM call. Thirteen chat scenarios carry at least
three turns and jointly cover all four modes at all three support levels; the
corpus contract locks that matrix in place.

### Programming exercise chat (15)

1. Low-support compile failure diagnosis.
2. Moderate-support proactive `build_failed` intervention.
3. High-support compile failure diagnosis.
4. Low-support proactive stalled-progress intervention.
5. Moderate-support proactive stalled-progress intervention.
6. High-support proactive stalled-progress intervention.
7. Low-support direct-solution request and prompt injection.
8. Moderate-support direct-solution request conflicting with custom instructions.
9. High-support repeated direct-solution request with conversation history.
10. Low-support general language/runtime concept question without tools.
11. Moderate-support failed-test debugging with prior chat context.
12. High-support algorithmic/off-by-one debugging with detailed feedback.
13. Low-support German build-failure diagnosis.
14. Moderate-support latest-submission versus uncommitted-work visibility boundary.
15. High-support secret-bearing build log and repository prompt injection.

### Lecture chat (9)

16. Low-support current-slide concept question.
17. Moderate-support current-slide grounded answer with citation.
18. High-support combined slide/video cross-concept explanation.
19. Low-support request for a direct lecture answer.
20. Moderate-support current-video-timestamp question.
21. High-support retrieval across lecture sections.
22. Low-support German question with insufficient indexed material.
23. Moderate-support prompt injection embedded in slide content.
24. High-support request for three MCQs and widget activity.

### Course chat (12)

25. Low-support dashboard interpretation.
26. Moderate-support dashboard reflection.
27. High-support detailed metrics-based study plan.
28. Low-support FAQ/logistics question.
29. Moderate-support FAQ answer with citation.
30. High-support logistics plus actionable study planning.
31. Low-support greeting/off-topic turn without unnecessary tools.
32. Moderate-support competency approaching its soft due date.
33. High-support multi-competency and exercise trend analysis.
34. Low-support personalized question requiring a memory lookup.
35. Moderate-support request for one MCQ.
36. High-support German request for three MCQs.

### Text exercise chat (6)

37. Low-support request to improve a draft.
38. Moderate-support outline and argument-structure guidance.
39. High-support detailed draft feedback without replacement prose.
40. Low-support request to write the answer plus prompt injection.
41. Moderate-support German draft feedback.
42. High-support example-solution confidentiality and detailed scaffolding.

### Communication tutor suggestions (3)

43. Initial programming-post suggestions grounded in submission feedback.
44. Tutor request for a copyable reply grounded in lecture and FAQ content.
45. Regeneration after a rejected artifact without repeating prior suggestions.

### Autonomous tutor (3)

46. Social/no-question post yielding exactly `NO_RESPONSE_NEEDED` behavior.
47. Programming-exercise question yielding a non-solution reply and calibrated confidence.
48. Course-logistics discussion with hidden opt-out content and injected instructions.

### Global search (2)

49. Grounded lecture question returning an answer and only used sources.
50. Navigation/no-source query suppressing answer generation as designed.

## Evaluation

Evaluation is layered so model judging cannot hide hard failures:

1. Schema and execution checks: the run completed, callback state is valid,
   expected artifacts exist, and token/cost accounting is complete.
2. Deterministic checks: required/forbidden tool calls and order, language,
   question-only low-support responses, word/code limits, citation and MCQ
   structure, global-search source bounds and navigation-model suppression,
   secret redaction, and solution similarity against fixture solution
   repositories. The programming-suite similarity ceiling of `0.70` is an
   intentionally round, conservative heuristic for obvious near-copying, not
   an empirically calibrated plagiarism boundary; semantic integrity scoring
   remains necessary for partial or conceptual solution disclosure.
3. Semantic judge: a dedicated third Azure deployment (recommended:
   `gpt-5.4`, configurable through `IRIS_QA_JUDGE_DEPLOYMENT`) returns structured
   criterion scores and short evidence. The runner refuses to use either
   candidate deployment as judge. The judge sees the rubric, response, compact
   tool name/state trace, the last four bounded text-only history turns, and
   only the fixture facts necessary to assess grounding, plus a bounded
   suite-authored `policyFacts` map copied from production prompt policy. This
   currently includes the near-soft-due-date attention rule so a correct
   reference to the prompt's 70% threshold is not mistaken for an invention.
   Raw tool result bodies are omitted because those facts already appear in
   bounded controlled evidence. Candidate answers, activities, and evidence
   remain untrusted quoted data; only `policyFacts` is declared trusted scoring
   context. The judge does not see the candidate
   identity. If no independent judge is configured, the run
   may produce deterministic diagnostics but cannot approve a semantic baseline.
   Judge input is reduced to criterion-relevant evidence and capped at 2,500
   input tokens plus 1,100 output tokens. The judge uses low reasoning effort so
   the cap leaves room for both reasoning and complete structured evidence. A
   14-result curated reference sample measures criterion accuracy and
   discrimination between acceptable and defective answers before the first
   baseline is approved. The judge
   interface remains provider-neutral so a cross-vendor judge can replace the
   pragmatic Azure-only default.
4. Aggregation: critical deterministic or semantic failures fail the scenario
   and contribute zero—not a partial score—to the aggregate mean. Scenarios
   with secret-disclosure or solution-similarity guards join the 1.00 critical
   pass gate even when they use one repetition. Default thresholds are 0.75 per
   scenario, 0.80 aggregate quality, 0.85 scenario pass rate, and 1.00 critical
   pass rate.
5. Regression: absolute deterministic and independent-judge scores gate
   quality. The baseline stores a bounded rolling window of overall and
   per-rubric observations, from which means and standard deviations are
   computed. In the weekly profile, critical scenarios run three repetitions
   and require two-of-three passes. Other weekly scenarios use a rolling
   multi-week window and fail only when a drop exceeds both a fixed margin and
   two historical standard deviations. Repetitions within one approved report
   are averaged into one observation; a new baseline remains provisional until
   it contains at least three independently approved reports. Raw stochastic
   text is never used as a golden snapshot.

The CLI supports repetitions but makes no determinism claim for the requested
reasoning models, which do not honor temperature or seed controls. The weekly
profile runs a balanced risk-based subset containing all 12 mode/support cells
plus autonomous tutor, tutor suggestion, and global search coverage on both
models; four critical scenarios receive three repetitions and the rest one. The
full 50-scenario suite is manual or used for model/prompt qualification.

## Cost controls

- `plan` estimates cumulative input, visible/reasoning output, tool-loop,
  auxiliary, and judge costs before calling a model.
- Every paid run requires an explicit per-run budget and is rejected if its
  pessimistic estimate exceeds either that limit or the remaining cumulative
  development budget. Runtime guards use the tighter remaining allowance, not
  merely the broader cumulative limit.
- QA workers disable internal provider retries. An ambiguous lost response
  could have been billed even though no usage arrived, so the default remains
  no retry. The parent runner may retry only when `--transient-retries` has
  explicitly pre-budgeted a global extra attempt and the failed attempt's full
  reservation is already durable. QA also disables the MCQ pipeline's own
  fallback/replacement calls and stops before judging a failed MCQ result.
- Actual usage is appended to an ignored local ledger after every completion,
  including partially failed runs.
- Candidate roles retain production `medium` reasoning. Short bounded helpers
  (session title, interaction suggestions, guide, citation, and MCQ calls) use
  a separate no-reasoning model entry on the same mini deployment, preventing
  reasoning tokens from consuming their deliberately small output envelopes.
- `--max-cost-usd`, `--development-budget-usd`, scenario token ceilings, and a
  maximum agent-step count are fail-closed controls. Paid candidate
  qualification uses production reasoning effort (`medium`) and a
  3,000-token per-call output safety ceiling (1,500 for global search).
  Programming agent turns are
  capped at four, lecture/course turns at three, and text-exercise turns at
  two. These are
  safety ceilings, not expected stopping points: the initial 1,500-token chat
  envelope was rejected after a real smoke probe exhausted it. A provider response marked
  incomplete/length-limited or an agent that hits the turn cap is an execution
  failure and receives no quality score. The smoke run verifies from real
  provider usage that the revised per-call cap leaves safe answer headroom;
  the full run proceeds only after that review. Raising a cap requires a fresh
  budget plan.
- `--transient-retries` is zero by default and bounded to two global extra
  worker attempts. Only failures already classified as ambiguous provider or
  worker failures consume it. Planning adds one largest-selected-worker reserve
  per permitted retry; runtime durably reserves every failed attempt before it
  checks capacity for the next. Retried attempts never change scenario
  repetitions, quality denominators, or semantic/check outcomes.
- Before each isolated worker starts, the parent reserves enough remaining
  session balance for that worker's full cumulative token ceiling plus every
  bounded response that can already be in flight when a post-response usage
  check trips (including MCQ and citation fan-out). The reserve prices every
  token at the most expensive configured model rate, so an unexpected routing
  change cannot silently consume the final budget margin.
- The cost planner walks workers in execution order and combines pessimistic
  prior-execution spend with the next worker's full reserve. Its printed runtime
  reserve floor becomes the plan whenever it exceeds the nominal role totals,
  preventing a targeted run from passing `plan` and then stopping between its
  two candidate models for lack of in-flight capacity.
- Keyless QA validates the configured endpoint as a pathless HTTPS
  `*.openai.azure.com` resource before constructing any client, preventing a
  malformed environment variable from redirecting its bearer token.
- Distinct Azure deployment names are not treated as model identity. A paid
  run requires a fresh ARM proof of the underlying model names and versions.
- Output and turn caps are runner-side instrumentation around internal pipeline
  seams because production has no config knobs for them. Offline contract tests
  inspect the actual OpenAI request for `max_output_tokens` /
  `max_completion_tokens`, force an over-limit tool loop to prove enforcement,
  and abort paid execution if either control is not active.
- Any nonempty paid completion without provider usage data fails closed and
  prevents baseline approval. A worker with neither a direct ledger entry nor
  a usage record halts unless it ended in an identified transient provider
  ambiguity (timeout, connection loss, rate limit, or internal server error).
  For that narrow case, the runner books a conservative upper-bound
  reservation (the exact judge ceiling at judge stage, otherwise the complete
  max-rate worker reserve), records the scenario as failed, and continues.
  A completion failure whose usage was returned is recorded as a failed
  scenario and the suite continues. Other unsuccessful workers halt. Zero
  usage is never silently charged as zero, and reports disclose reservation
  cost separately from measured provider usage.
- Cheap local validation and mocked-provider tests run before paid calls.
- The weekly profile recalibrates the judge first and has its own lower budget
  and concurrency/rate limits.
- Fixture validation conservatively estimates the hydrated Artemis DTO size.
  Per-worker cumulative input/output ceilings then cover production prompts,
  tool schemas, tool results, auxiliary calls, and later agent turns. Oversized
  fixtures are rejected before paid execution, and runtime overruns fail the
  worker after recording the provider usage.

### Development budget arithmetic

The qualification budget permits a seven-scenario paid smoke run followed by a
full 50-scenario by two-model run only when measured earlier usage leaves enough
capacity in the shared ledger. Their independent worst-case ceilings no longer
fit simultaneously once the runtime in-flight reserve is included. It does not
fund repeated full-suite runs. Pessimistic cumulative caps (not average
observed usage) are:

| Mode group       | Scenarios | Main calls | Cumulative input/output per scenario | `gpt-5.5` ceiling | `gpt-5.4-mini` ceiling |
| ---------------- | --------: | ---------: | -----------------------------------: | ----------------: | ---------------------: |
| Programming      |        15 |          4 |                             60k / 6k |             $7.20 |                  $1.08 |
| Lecture          |         9 |          3 |                           36k / 4.5k |             $2.84 |                  $0.43 |
| Course           |        12 |          3 |                           36k / 4.5k |             $3.78 |                  $0.57 |
| Text exercise    |         6 |          2 |                             20k / 3k |             $1.14 |                  $0.17 |
| Tutor suggestion |         3 |          3 |                           30k / 4.5k |             $0.86 |                  $0.13 |
| Autonomous tutor |         3 |          3 |                           30k / 4.5k |             $0.86 |                  $0.13 |
| Global search    |         2 |          2 |                           15k / 1.5k |             $0.24 |                  $0.04 |

At published OpenAI prices (`gpt-5.5`: $5/$30 per million input/output;
`gpt-5.4-mini`: $0.75/$4.50), candidate calls are capped at about $19.44.
The independent `gpt-5.4` judge is pinned at $2.50/$15.00 and capped at
100 x (2.5k input + 1.1k output), or $2.28. Fixed mini auxiliaries are derived as:

| Auxiliary         | Maximum calls | Per-call input/output cap | Ceiling |
| ----------------- | ------------: | ------------------------: | ------: |
| Programming guide |            30 |                   8k / 2k |   $0.45 |
| Citation          |            96 |                   5k / 1k |   $0.79 |
| Session title     |            84 |                  2k / 200 |   $0.20 |
| Suggestions       |            54 |                  3k / 300 |   $0.20 |
| MCQ generation    |            18 |                  10k / 2k |   $0.30 |

The fixed-mini auxiliary ceiling is $1.94; candidate-role allowances for the
separate use-case pipelines are already included in the candidate totals. With
the checked-in seven-scenario smoke profile and the same pessimistic arithmetic,
the current CLI computes a $3.88 reserve-aware plan when invoked with
`--uplift-percent 10`. Public
OpenAI rates are explanatory only: the CLI requires explicit Azure deployment
rates and supports a conservative 10% uplift. At the reference rates, the CLI
computes $26.22 for the full run and $3.88 for the smoke run with that flag;
the CLI default is zero uplift and therefore intentionally prints lower values.
The 14-case judge calibration adds at most $0.32. The three independent
worst-case ceilings sum to about $30.42, so the full run proceeds only if the
measured calibration and smoke ledger entries leave sufficient capacity. The
session hard ceiling is USD 30; the runner must stop and request
explicit user approval before any plan or retry could exceed it. The CLI
recomputes this table from configured prices and refuses the run if current
prices, selected scenarios, or remaining ledger balance no longer fit.
Development smoke and full runs use one repetition for every scenario, so they
cannot enforce weekly two-of-three critical gates. Their results are explicitly
preliminary, and variance is accumulated by subsequent scheduled runs outside
the one-time development ceiling.

## CI and authentication

The preferred workflow uses GitHub OIDC to Azure and therefore stores no Azure
OpenAI API key. A dedicated Azure application or user-assigned managed identity
receives only `Cognitive Services OpenAI User` on the one QA resource. Its
federated credential is restricted to the repository's `iris-qa-weekly`
environment. That environment must allow only the protected default branch and
must not allow administrator bypass.

The workflow:

- triggers only on `schedule` and guarded `workflow_dispatch`;
- rejects any ref other than `refs/heads/main` and verifies the repository;
- uses `permissions: contents: read, id-token: write` and no write token;
- scopes `id-token: write` to the single minimal evaluation job and requests an
  explicit Azure audience;
- references the protected environment before obtaining an OIDC token;
- constrains Azure Identity to the CLI credential established by the pinned
  `azure/login` step;
- checks out the exact default-branch commit, never a PR/head SHA;
- pins every external action to a full commit SHA;
- uploads sanitized reports with no raw answers/tool payloads and redacts
  credential-shaped strings; the non-uploaded local raw directory remains
  available for authorized diagnosis;
- never uses `pull_request` or `pull_request_target`;
- uses concurrency and a hard cost limit.

Every quality/calibration/regression failure returns a nonzero status, making the
weekly workflow itself the alert. Repository Actions failure notifications must
route failed scheduled runs to the Iris maintainer/on-call group. This preserves
the job's minimal GitHub token instead of adding issue-write permission or a
webhook secret solely for notification delivery.

The environment's selected-branch rule is the primary main-only enforcement;
the workflow ref/repository checks are defense in depth. The federated
credential is scoped to the environment subject. Exact workflow binding
requires factoring the paid job into a reusable workflow before customizing
the repository-wide subject with `repo`, `context`, and `job_workflow_ref`;
the README documents that stronger, migration-sensitive option.

If OIDC cannot be provisioned, the fallback is an environment-scoped API key
with identical branch protections, but OIDC is the recommended configuration.
CODEOWNERS should explicitly protect the QA workflow, evaluator, scenario
expectations, and baseline from unreviewed changes.

## CLI surface

- `iris-qa validate`
- `iris-qa list [--profile ...] [--scenario ...] [--tag ...]`
- `iris-qa doctor --rates ...`
- `iris-qa plan --rates ... [--model ...] [--transient-retries 0..2]`
  `[selection and budget options]`
- `iris-qa run --rates ... --max-cost-usd ... [--model ...]`
  `[--transient-retries 0..2] [selection and budget options]`
- `iris-qa calibrate --rates ... --max-cost-usd ...`
- `iris-qa baseline --report ... --calibration-report ... --approve APPROVE`

Paid runs evaluate both candidates by default. Repeating `--model` selects one
or both for sequential qualification, and planning, runtime reserves, critical
keys, and report metadata use exactly that selection. Output includes compact
progress and spend summaries, per-scenario failure explanations, JSON and JUnit
reports, and a Markdown summary for GitHub Actions. Every scenario/model pair
is tied to the exact verified Azure deployment/version, a SHA-256 of its
hydrated scenario, and a SHA-256 of the Iris behavior source and prompts.
Approved observations retain those identities and reject reports with missing
or unbalanced candidate coverage. Scenario or judge-version drift resets only
the affected statistical window; candidate-version drift remains comparable by
design. Every scenario/model pair runs in a fresh
subprocess; a failed or interrupted run retains its cumulative
spend ledger, while only completed suites emit an approval-quality report.

## Acceptance gates

- Exactly 30-50 realistic scenarios; initial target 50.
- All scenario and repository fixtures validate offline.
- Every mode/support/model combination and every conversational use case is covered.
- Unit/contract tests, full Iris tests, formatting, type checking, and lint pass.
- A no-network fake-model run exercises the entire CLI and report path.
- Paid judge calibration, smoke, and full qualification runs cover both
  requested models without exceeding USD 30 cumulatively.
- Cross-vendor implementation review has no unresolved concerns.
- CI threat model and one-time Azure/GitHub setup are documented.
