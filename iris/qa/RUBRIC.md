# Rubric for chat answers

Every chat situation in the corpus (42 of 50) is rated on the same five criteria. They describe what
a student gets out of an answer, not how the answer was produced. The wording the judge sees is in
[`rubric.py`](../src/iris/qa/rubric.py); this page explains it.

## The five criteria

Each criterion is rated `achieved` (100), `partly_achieved` (50) or `not_achieved` (0).

| Criterion        | The question                                                                                         |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| `trustworthy`    | Is what the answer states as fact correct, grounded in the evidence Iris had, and honest about gaps? |
| `moves-forward`  | After reading it, does the student know what to do next, and was their real question dealt with?     |
| `keeps-thinking` | Does it leave the thinking to the student at the instructor's support level, with no copyable work?  |
| `easy-to-follow` | Is it clear and short enough to use, in the student's language, without padding or repetition?       |
| `encouraging`    | Does the tone support the student without flattery, talking down or false reassurance?               |

### What the support level means

The production prompt gives every support level the same hard rule: Iris never hands over a solution,
a complete implementation or content the student can copy into their own task. The levels differ in
how much help comes with it.

| Support  | Amount of help                                                                              |
| -------- | ------------------------------------------------------------------------------------------- |
| low      | Minimal: short, guiding questions and pointers to the problem statement, slides or lecture. |
| moderate | Explains the concept and points at the area of the problem, with small hints.               |
| high     | Detailed conceptual walkthroughs and reasoning, with examples from a different domain.      |

Questions that are not the student's own task (a definition, course logistics, what a lecture says)
may be answered directly at every level. `keeps-thinking` is rated against this, so a long answer is
a problem at low support and a plain refusal of a factual question is a problem at every level.

## Reference entries

A rubric only works if the judge knows what is true in the situation. Every chat scenario therefore
carries 2 to 8 `reference` entries in its YAML file. They are ground truth for the judge, not an
expected answer, and they never prescribe wording. Each entry starts with a tag:

| Tag         | Use                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------- |
| `FACT`      | Something true here that the judge needs to check the answer's claims.                            |
| `NEED`      | What the student actually needs to make progress, including the real problem behind the question. |
| `HOLD BACK` | What the answer must not hand over at this scenario's support level.                              |
| `TRAP`      | A tempting wrong answer or misleading detail the scenario is built around.                        |
| `LANGUAGE`  | The language the answer should use, when it is not English.                                       |

Every scenario has at least one `NEED`. Verify each `FACT` in the fixtures before writing it down; a
wrong reference entry turns into a wrong rating.

## Critical incidents

Critical errors stay separate from the five ratings. They are binary, listed per scenario in
`critical_errors`, and the judge decides for each whether it actually happened. They are never
averaged into a score.

## Numbers in the report

- **IrisScore**: equal-weight average of the criterion points per scenario, then over scenarios.
- **Usable answers**: the share of chat answers with no critical error where neither `trustworthy`
  nor `moves-forward` is `not_achieved`. This is a floor: it counts the answers that fail the
  student, not how good the rest are. It is the number to read first.
- **Usage-weighted**: the chat-mode means weighted by the approximate share of chat messages per
  mode in real use (programming 78%, course 14%, lecture 7%, text 1%), so a rarely used mode cannot
  move the headline. Update `CHAT_MODE_USAGE_WEIGHTS` when usage shifts.
- **By rubric criterion**: the mean points per criterion, to see what a model is weak at.

The 22 advanced situations are rated on the same five criteria. Their difficulty lives in the
reference entries (conflicting sources, hidden errors), so read the `difficulty` breakdown as the
capability score and the foundation rows as everyday quality.

## Using the rubric responsibly

- An LLM judge has known biases: it prefers longer answers, its own model family and the first
  answer it sees. Candidates are blinded, the judge is never the candidate, and a judge should be
  calibrated against a stronger reference or human ratings before its scores are trusted. Report
  agreement as weighted Cohen's kappa, not as raw percent agreement.
- The scenarios are synthetic and longer than real student messages (a real message is a few words,
  often a follow-up). Treat scores as a comparison between models and prompts, not as a measure of
  what students experience.
- The benchmark measures the answer, not learning. A student who gets a polished answer can still
  learn less, so keep `keeps-thinking` weighted equally with the rest.

## Adding or changing a scenario

1. Write the situation and its fixtures as before.
2. Do not add `criteria` to a chat scenario; the loader fills in the five.
3. Add 2 to 8 `reference` entries with the tags above.
4. Run `iris-benchmark validate`.

Non-chat scenarios (tutor suggestions, autonomous tutor, global search) keep three to five criteria
of their own, because their output is not a student-facing answer.
