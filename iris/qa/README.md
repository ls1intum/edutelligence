# Iris quality assurance

This directory contains a source-grounded, real-model regression suite for the
student-facing Iris pipelines. It tests behavior rather than exact wording.
The checked-in corpus has 50 synthetic but realistic scenarios, including all
four unified chat modes at low, moderate, and high support, communication tutor
suggestions and autonomous tutor decisions spanning the same three wire-level
support settings, and global search. Current Iris tutor/autonomous prompts do
not branch on that setting; the explicit cases preserve the input combination
and will expose future behavior drift.

Thirteen conversational scenarios contain realistic prior user/assistant turns,
covering every chat-mode/support-level combination. The remaining cases keep
history intentionally short when the behavior under test is a clean first
request. The semantic judge receives only the last four text turns, each
length-bounded, so it can assess continuity without copying attachments or
unbounded transcript data into a second model call. Persisted turns retain
Artemis message IDs, chronological timestamps, and polymorphic content types;
one course scenario also carries a previously answered raw-JSON MCQ.
Every scenario also declares a synthetic UTC instant. The adapter freezes the
production prompt and deadline-tool clock at that value, so fixed course dates
do not silently change meaning in later weekly runs.

## What is exercised

The worker calls the production pipeline classes, prompt templates, model
bindings, agent loop, tools, programming guide, citations, MCQ generation,
titles, and suggestions. Only external systems are replaced: retrieval results,
Memiris storage, and Artemis callbacks come from fixtures. Azure model calls are
real. Each scenario is run in a new process so Iris's import-time configuration
and singletons cannot leak between model profiles.

Programming fixtures include template, solution, test, and several student
repository snapshots plus `submission-history.yml`. The DTO sent to Iris still
matches Artemis: only the latest submitted repository is on the wire; the
history and uncommitted working tree are QA provenance used to test visibility
boundaries.
Offline tests execute the Python reference/failing snapshot and, when a JDK is
available, compile and run the Java reference, hidden-test failure, and compiler
failure snapshots to prove that the recorded histories remain reproducible.

## Local usage

Use Python 3.13 and Poetry from the `iris` directory:

```bash
poetry install
poetry run iris-qa validate
poetry run iris-qa list --profile smoke
```

Copy `qa/config/rates.example.yml` to the ignored
`qa/config/rates.local.yml`, replace the reference prices with confirmed Azure
deployment prices, and set `confirmed_azure_rates: true`. A paid command will
not accept an unconfirmed rate card.

If your normal ignored Iris configuration already contains the Azure endpoint
and API key, reuse it directly instead of exporting those values one by one.
Exact `gpt-5.4-mini`, `gpt-5.5`, and `gpt-5.4` entries supply their custom Azure
deployment names when present; otherwise those three names are used as the
deployment defaults. The global option must come before the subcommand:

```bash
poetry run iris-qa --llm-config llm_config.local.yml doctor \
  --rates qa/config/rates.local.yml
poetry run iris-qa --llm-config llm_config.local.yml run \
  --profile smoke --rates qa/config/rates.local.yml \
  --deployment-verification qa-results/deployments.json \
  --max-cost-usd 3.88 --development-budget-usd 30 \
  --uplift-percent 10 --output qa-results
```

The bridge reads the key only into the worker environment and writes generated
model configuration with an environment-variable reference, never the key
itself. Files matching `llm_config*.local.yml` are ignored. The ARM deployment
proof is still required so an inference key cannot silently redirect the QA run
to different model deployments.

For keyless Azure authentication, log in with an identity that has only
`Cognitive Services OpenAI User` on the QA Azure OpenAI resource, then set:

```bash
export IRIS_QA_AZURE_ENDPOINT=https://RESOURCE.openai.azure.com
export IRIS_QA_AZURE_AUTH_MODE=azure_ad
export IRIS_QA_AZURE_RESOURCE_GROUP=RESOURCE_GROUP
export AZURE_SUBSCRIPTION_ID=SUBSCRIPTION_ID
export IRIS_QA_GPT_54_MINI_DEPLOYMENT=DEPLOYMENT_NAME
export IRIS_QA_GPT_55_DEPLOYMENT=DEPLOYMENT_NAME
export IRIS_QA_JUDGE_DEPLOYMENT=INDEPENDENT_GPT_54_DEPLOYMENT
poetry run iris-qa doctor --rates qa/config/rates.local.yml
account_name="${IRIS_QA_AZURE_ENDPOINT#https://}"
account_name="${account_name%%.*}"
az cognitiveservices account deployment list \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --resource-group "$IRIS_QA_AZURE_RESOURCE_GROUP" \
  --name "$account_name" --only-show-errors --output json \
| poetry run python qa/scripts/verify_azure_deployments.py \
    --output qa-results/deployments.json
poetry run iris-qa plan --profile smoke \
  --rates qa/config/rates.local.yml \
  --development-budget-usd 30 --uplift-percent 10
poetry run iris-qa run --profile smoke \
  --rates qa/config/rates.local.yml \
  --deployment-verification qa-results/deployments.json \
  --max-cost-usd 3.88 --development-budget-usd 30 \
  --uplift-percent 10 --output qa-results
```

For a first qualification, run the judge calibration first, then the smoke
profile above. Inspect its answers, activities, provider usage, and output-cap
headroom before planning the full profile. Only if the smoke result is sound,
continue with:

```bash
poetry run iris-qa plan --profile full \
  --rates qa/config/rates.local.yml \
  --development-budget-usd 30 --uplift-percent 10
poetry run iris-qa run --profile full \
  --rates qa/config/rates.local.yml \
  --deployment-verification qa-results/deployments.json \
  --max-cost-usd 26.23 --development-budget-usd 30 \
  --uplift-percent 10 --output qa-results
```

If the cumulative guard cannot reserve one pessimistic full-model invocation,
run disjoint scenario shards sequentially and combine them without another model
call. The merge command requires an explicit target profile, verifies the exact
current scenario and Iris-source fingerprints, model/deployment/rate/threshold
compatibility, rejects duplicate observations, and fails closed if even one
expected scenario repetition is missing:

```bash
poetry run iris-qa merge --profile full \
  --report qa-results/shard-a/<run-id> \
  --report qa-results/shard-b/<run-id> \
  --output qa-results/merged
```

Each merged directory contains the same `report.json`, `report.md`, and
`junit.xml` formats as a direct run. It also records the source run IDs and
absolute report paths for auditability. If shards used a rolling baseline, pass
the same immutable baseline file with `--baseline`; merge recomputes regression
gates over the full union.

To qualify candidates sequentially, add `--model gpt-5.4-mini` to both `plan`
and `run`, finish that qualification, and then repeat with `--model gpt-5.5`.
Omitting `--model` keeps the weekly/default behavior and evaluates both. A
mini-only run requires verified mini/auxiliary and judge deployments; a 5.5 run
also requires the mini auxiliary deployment.

Both commands include the earlier calibration and smoke usage through the same
default ledger. They fail closed if confirmed prices or the remaining balance
no longer fit. Do not manually rerun an interrupted paid run without inspecting
the ledger and making a fresh plan; use `--transient-retries` only when the
current invocation should pre-budget bounded ambiguous-failure recovery.

`poetry run iris-qa doctor --rates qa/config/rates.local.yml` validates the
endpoint, auth mode, rates, and three distinct deployments without obtaining a
credential or making a model request. The weekly workflow runs this preflight
before its OIDC login. The ARM listing after login then proves that those names
currently serve `gpt-5.4-mini`, `gpt-5.5`, and the independent `gpt-5.4` judge.
The paid CLI accepts only a proof matching its endpoint and environment that is
at most one hour old, and records the returned model versions in its report.

API-key auth is available for local fallback only. Set
`IRIS_QA_AZURE_AUTH_MODE=api_key` and `IRIS_QA_AZURE_API_KEY`; generated model
configuration contains only the environment-variable name, never the key. The
paid command still requires a deployment proof produced by an Entra identity
with read-only deployment access; the API key cannot attest which model Azure
serves.

The spend ledger is append-only, mode `0600`, records every provider call
immediately, and uses an exclusive per-ledger run lock so two local paid
commands cannot consume the same remaining balance. A run is refused when its
pessimistic plan exceeds either `--max-cost-usd` or the cumulative
`--development-budget-usd`. Missing token usage, response truncation, and agent
turn-cap exhaustion fail closed. Paid QA also disables automatic provider
retries because a lost response may already have been billed. The live ledger
guard uses the tighter of the remaining invocation allowance and cumulative
allowance; each worker (and each calibration case) must fit its complete
in-flight reserve before a request starts. A worker with no provable usage
normally halts the suite immediately. An identified transient provider error is
the narrow exception: the ledger immediately books a conservative upper-bound
reservation for the ambiguous call. By default the scenario fails and the
suite continues. The optional `--transient-retries N` permits at most `N` extra
worker attempts globally for only those already-classified ambiguous failures.
Each retry requires another complete worker reserve, preserves the failed
attempt's raw output, and does not add a scenario repetition or quality
observation. Provider failures that return complete usage are likewise recorded
as failed scenarios and do not abort the remaining suite; semantic/check
failures are never retried, and unclassified failures without usage still stop.
Calibration remains sequential and stops on its first failed case. If that
judge worker times out or exits without any recorded usage, the ledger reserves
one complete judge-call ceiling before stopping, so a later manual rerun cannot
forget a possibly billed call.
The optional local paid deployment attestation applies the same rule per tiny
probe; the CI workflow uses the non-inference ARM listing instead.

For small targeted selections, the largest in-flight worker reserve can exceed
the sum of nominal model ceilings. `plan` therefore prints a runtime reserve
floor that includes pessimistic spend from preceding executions and uses the
larger value as its final plan. Copying that exact plan into `--max-cost-usd`
will not be rejected halfway through an otherwise valid sequential run.

The CLI's uplift and transient-retry defaults are both zero. Local qualification
commands explicitly pass `--uplift-percent 10`; cost figures in the architecture
document assume that flag. At the checked-in reference rates the pessimistic
smoke and full plans are $3.88 and $26.22 after applying the runtime reserve
floor. Together with the roughly $0.32 judge calibration, their simultaneous
worst-case sum is
$30.42. The CLI therefore starts the full qualification only when measured
calibration and smoke usage in the shared ledger leave enough of the $30
ceiling; it never assumes all three worst cases can be spent.

## Assessment and baselines

Hard checks cover response presence, language, support-level behavior, required
and forbidden tools, citations, MCQ structure, secret disclosure, and source
solution similarity, plus session titles, interaction suggestions, and
autonomous confidence ranges. A blinded independent `gpt-5.4` judge scores weighted
scenario rubrics. The judge deployment must differ from both candidates.

The programming solution-similarity ceiling is `0.70`. This is deliberately an
initial, conservative heuristic for catching obvious near-copies rather than a
claimed empirical plagiarism boundary. It complements, but does not replace,
the semantic integrity rubric; calibrating it against labeled safe, borderline,
and disallowed examples is future validation work.

The absolute gates are:

- score at least 0.75 per scenario;
- aggregate mean at least 0.80;
- scenario pass rate at least 0.85;
- every critical group passes (weekly critical cases use two of three).

The rolling baseline is deliberately empty until a passing report is reviewed.
First calibrate the independent judge against the 14 curated reference examples;
one defective answer directly attempts to override the evaluator and award
itself full credit, a task-specific low-support explanation verifies the
questions-only production rule, and a clean greeting verifies both the greeting
exception and that omitting irrelevant private metrics is not mis-scored as
missing personalization. This is a paid check capped at roughly $0.32 at the
reference judge rate:

```bash
poetry run iris-qa calibrate --rates qa/config/rates.local.yml \
  --deployment-verification qa-results/deployments.json \
  --max-cost-usd 0.32 --development-budget-usd 30 \
  --output qa-results/judge-calibration.json
```

Approval is explicit and requires the passing calibration artifact:

```bash
poetry run iris-qa baseline --report qa-results/RUN/report.json \
  --calibration-report qa-results/judge-calibration.json \
  --output qa/baseline.json --approve APPROVE
```

The calibration artifact is bound to the exact Azure judge deployment and model
version recorded in the candidate report; a result from another judge cannot be
used to approve its baseline.

Regression gates begin after three approved reports per scenario/model. Multiple
repetitions in one report are averaged into one observation, so repeated samples
from a single week cannot manufacture a multi-week baseline.
A regression must exceed both 0.05 and two historical standard deviations;
overall and individual rubric dimensions are checked. Candidate results remain
separate so model-specific regressions cannot be hidden by an aggregate score.
The weekly job deliberately never rewrites the baseline. A maintainer reviews a
passing weekly artifact, runs the explicit `baseline` command locally, and
commits the bounded observation update through normal code review. This keeps a
bad or compromised model run from teaching the gate that its own regression is
normal. The weekly job does rerun the inexpensive judge calibration before the
candidate suite. Weekly CI replaces the generic uplift with one explicitly
priced global transient retry. At the reference rates, calibration plus the
resulting approximately $20.22 weekly plan is about $20.54 under its independent
$21 cumulative ceiling. The candidate run itself retains a separate $20.51
invocation ceiling.

Any calibration, absolute-quality, safety, or regression-gate failure exits
nonzero, marks the scheduled workflow failed, and leaves its Markdown/JUnit/JSON
evidence in the run summary and artifacts. Configure repository Actions failure
notifications for the Iris maintainer or on-call group; the workflow deliberately
does not gain `issues: write` or carry a webhook secret merely to send alerts.
Reports include sanitized per-model call/token maxima and run/cumulative cost so
maintainers can verify output-cap headroom without publishing prompts or the raw
spend ledger. Publishable JSON omits raw answers and tool results and all three
report formats redact credential-shaped strings. Full raw worker output remains
under the local run directory for authorized diagnosis; CI never uploads it.
Reports also preserve SHA-256 fingerprints for each hydrated
scenario and the complete Iris behavior source/prompt tree, plus the verified
Azure deployment model versions. Approved baseline observations retain that
provenance and require balanced results from both candidates. A changed
scenario or calibrated judge starts a fresh three-report provisional window;
candidate version changes deliberately continue against the existing window so
model-update regressions remain visible.

## GitHub and Azure security setup

The weekly workflow uses OpenID Connect, so there is no Azure OpenAI key to
print from a pull request. Configure a GitHub environment named
`iris-qa-weekly` with deployment branches restricted to protected `main` and
administrator bypass disabled. Add the identifiers, deployment names, and
confirmed prices used by the workflow as environment **variables**, not
secrets. This includes `IRIS_QA_AZURE_RESOURCE_GROUP`; the existing
`AZURE_SUBSCRIPTION_ID` is also exposed to the verification step.

The environment variable checklist is:

- identity: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`;
- resource: `IRIS_QA_AZURE_ENDPOINT`, `IRIS_QA_AZURE_RESOURCE_GROUP`,
  `IRIS_QA_AZURE_API_VERSION`;
- deployments: `IRIS_QA_GPT_54_MINI_DEPLOYMENT`,
  `IRIS_QA_GPT_55_DEPLOYMENT`, `IRIS_QA_JUDGE_DEPLOYMENT`;
- billing evidence: `IRIS_QA_RATE_SOURCE` and the six
  `IRIS_QA_*_{INPUT,OUTPUT}_RATE` values shown in the workflow.

None is a credential. The federated identity is the only authority granted to
the job, and its deployment listing is read-only.

Create a dedicated Entra application or user-assigned managed identity with one
federated credential. Its subject must be exactly:

```text
repo:ls1intum/edutelligence:environment:iris-qa-weekly
```

Use audience `api://AzureADTokenExchange`. Grant only `Cognitive Services
OpenAI User`, scoped to the one QA resource. Do not grant Contributor, Owner,
deployment management, role assignment, or access to unrelated Azure
resources. Azure's [keyless OpenAI guidance](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/managed-identity)
and GitHub's [Azure OIDC guidance](https://docs.github.com/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-azure)
describe the token exchange.

OIDC prevents stored-key extraction, but merged workflow code could still use
its short-lived token. Protect `.github/workflows/iris_qa_weekly.yml`, the QA
runner/evaluator, scenarios, and baseline with CODEOWNERS plus required reviews
and branch protection. The workflow has no PR trigger, rejects non-main refs,
checks out protected `main`, persists no Git credential, pins actions by full
commit SHA, receives a read-only GitHub token, and runs the complete offline
Iris/QA test suite before requesting an Azure token.

The default subject is environment-scoped, not workflow-file-scoped: another
workflow merged into protected `main` could reference the same environment.
For exact workflow binding, first factor the paid job into a protected reusable
workflow, then use GitHub's
[custom OIDC subject claims](https://docs.github.com/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect#customizing-the-token-claims)
with `repo`, `context`, and `job_workflow_ref`, and make the Azure federated
credential match that complete subject. `job_workflow_ref` is only present for
jobs running in a reusable workflow; do not add that claim to the current
single-file workflow. Subject customization is repository-wide and can break
other OIDC consumers, so inventory and migrate them together. A private,
ephemeral self-hosted runner plus Azure Private Link is the strongest network
boundary if available.
The workflow also constrains `DefaultAzureCredential` to the
`AzureCliCredential` established by `azure/login`, preventing fallback to a
different credential source on the runner.

The fallback environment-scoped API key is less safe. If it is unavoidable,
store it only in the protected environment, rotate it, keep this workflow free
of PR triggers and `pull_request_target`, and retain the same CODEOWNERS and
branch restrictions.
