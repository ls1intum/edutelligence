# Iris behavior changes retained for later review

## Status and purpose

This document records the Iris behavior changes developed alongside the first
QA suite. They are intentionally preserved on the
`iris/feature/quality-assurance` branch, but they are **not** the agreed
production design and should not be merged as one package.

The replacement benchmark must be made understandable and trustworthy before
these changes are reconsidered. At that point, each improvement should be
evaluated independently against the simpler benchmark and reviewed as an Iris
product change in its own right.

## Why these changes were introduced

Early real-model QA runs exposed recurring classes of problems:

- Iris sometimes answered without first obtaining the course, repository,
  submission, feedback, or learning-progress information needed for the claim.
- Low-support answers could contain the solution while merely ending with a
  question.
- Programming feedback sometimes treated an observed output as if it were an
  input and then claimed to reproduce a trace that the available data did not
  support.
- Citation, MCQ, tutor-suggestion, and structured-output pipelines were brittle
  when the model returned incomplete or slightly unexpected output.
- Some provider failures lost useful token-usage information, making cost
  accounting and retries unsafe.
- Retrieved text and build logs could contain instructions or credentials that
  should be treated as untrusted data.

The implementation tried to prevent those failures directly in production
code. Several individual ideas remain useful, but the combined implementation
became too large, too rule-driven, and too difficult to understand or maintain.

## Changes that may be worth revisiting

### 1. Fetching relevant data before answering

The chat pipeline gained an `authoritative_evidence` preflight step. It plans
and executes selected existing Iris tool providers before the main response and
adds their bounded results to the model context as untrusted data.

Potential value:

- gives the response model the actual Artemis state needed for factual claims;
- avoids claiming access to repositories, submissions, metrics, or deadlines
  that Iris did not retrieve;
- makes grounding available even if the model does not choose a tool itself.

Concern:

- the intent planner is largely hand-written and regex-based;
- it duplicates decisions that an agentic model and its tools should make;
- it adds a large parallel orchestration path to `ChatPipeline`.

If revisited, this should be redesigned as a small agent/tool-contract change,
not restored as the current preflight ruleset.

### 2. Support-level enforcement

The prompts and final response path were tightened so low, moderate, and high
support produce meaningfully different pedagogical help. Low support is meant
to remain Socratic, moderate support to give targeted guidance, and high
support to allow more explicit help without silently violating academic
integrity constraints.

Potential value:

- makes the instructor-controlled support setting observable in the answer;
- prevents a nominally low-support response from embedding the answer in a
  leading question;
- preserves direct factual answers for logistics questions where the support
  setting should not block useful information.

Concern:

- final-form enforcement grew into many English- and German-specific text
  heuristics;
- valid responses can be rewritten or rejected because of surface form;
- maintaining this approach across languages and future tasks is unrealistic.

The prompts and the intended support-level semantics are worth retaining as
design input. The regex-heavy response guard is not.

### 3. Programming feedback integrity

Programming chat gained a second review of the draft plus deterministic repair
logic. It tries to distinguish compiler/test observations from inputs, prevent
unsupported execution claims, avoid full-solution disclosure, retain verified
repository locations, and keep answers within support-specific size limits.

Potential value:

- addresses a real failure mode: treating an expected or observed output as an
  input and inventing a reproduction trace;
- keeps the guide model from removing correct diagnostics supplied by Artemis;
- makes submission-visibility boundaries explicit.

Concern:

- the repair logic parses arbitrary prose, code fragments, literals, and
  multilingual labels;
- deterministic reconstruction can itself become a second answer generator;
- the implementation is too tightly coupled to the scenarios that exposed the
  problems.

The underlying product requirements should become benchmark criteria first.
Only recurring failures should then motivate a smaller production change.

### 4. Prompt-injection and sensitive-data boundaries

Retrieved lecture text, FAQs, build logs, repository files, memories, and other
external content are marked as untrusted data. Prompts tell the model not to
follow embedded instructions or expose credential-shaped content. Tests cover
retrieval and programming-log injection cases.

Potential value:

- the trust boundary is valid independently of the benchmark;
- explicit separation of system instructions from retrieved content is easier
  to reason about than relying on model intuition alone.

Concern:

- some enforcement again depends on text-pattern matching;
- redaction and injection resistance need broader security review rather than
  being inferred from a small synthetic corpus.

Prompt-level trust-boundary wording and structured content separation are good
candidates for a later focused change.

### 5. Citation behavior

Citation handling was expanded to merge current-view and retrieved lecture
content, de-duplicate sources, preserve token usage, and attach a real source
when an evidence-grounded lecture answer otherwise lost lexical citation cues.

Potential value:

- better reflects what the student is currently viewing;
- reduces uncited grounded answers and duplicate citations;
- improves accounting and error isolation.

Concern:

- fallback citation selection can become policy-heavy;
- citation correctness needs to be assessed semantically, not merely by the
  presence of a citation payload.

### 6. MCQ and tutor-pipeline reliability

MCQ generation, interaction suggestions, communication tutor suggestions, and
autonomous tutor output gained stricter structured parsing, retries/fallbacks,
confidence handling, artifact preservation, and prompt-injection tests.

Potential value:

- these pipelines genuinely need graceful handling of incomplete structured
  model output;
- preserving a valid earlier artifact is often better than emitting nothing
  after a failed regeneration.

Concern:

- some fallbacks and retries may hide model regressions;
- each pipeline should define its own product contract and be evaluated
  separately rather than sharing one broad QA-driven hardening effort.

### 7. Provider authentication, usage, and retry handling

The Azure OpenAI client gained optional Entra token-provider support, clearer
API-key resolution, structured failure information, token-usage preservation,
and bounded retry behavior. The Ollama and request-handler paths were aligned
with related message and usage contracts.

Potential value:

- workload identity is preferable to a long-lived CI API key;
- usage must remain available when a request fails if cost guards are to be
  trustworthy;
- retry rules should distinguish known-unbilled setup errors from ambiguous
  provider failures that may already have incurred cost.

These changes are relatively independent of answer quality, but still require
normal focused review and tests before adoption.

### 8. DTO and message-conversion compatibility

Message content DTOs and converters were broadened to handle the Artemis wire
shapes used by synthetic histories, including text, JSON/MCQ, and image
content. Tool and pipeline DTOs gained small compatibility fixes uncovered by
running realistic fixtures through production constructors.

Potential value:

- some changes may be legitimate drift fixes between Artemis and Iris;
- realistic fixtures are useful contract tests even outside model evaluation.

These should be separated into narrow compatibility patches and confirmed
against current Artemis source before reuse.

## Recommended reuse process

After the simpler benchmark is established:

1. Record a baseline with unchanged production Iris.
2. Select one behavior problem, not one old code block.
3. Confirm that multiple realistic scenarios expose that problem.
4. Design the smallest general Iris change that addresses it.
5. Compare the new and baseline systems with the same benchmark and inspect the
   complete traces.
6. Keep the change only if it improves the relevant scenarios without causing
   meaningful regressions elsewhere.
7. Submit it as a focused change with its own explanation and tests.

This branch is therefore an archive of experiments and potentially useful
ideas. It is not a ready-made patch set to reapply wholesale.
