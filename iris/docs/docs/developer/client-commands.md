---
title: Client Commands
---

# Client Commands

A **command** lets a running pipeline ask Artemis to do something in the student's browser and learn whether it worked. It runs in the opposite direction from a status update: the pipeline blocks on the answer, because an agent that is about to write "look at the slide I just opened" has to know whether the slide was in fact opened.

Today there is exactly one command, the combined-view **point-out**: Iris moves the slides to a page or the video to a moment, then answers with that material in front of the student.

## The envelope

```python
class CommandDTO(BaseModel):
    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class CommandResultDTO(BaseModel):
    applied: bool
```

`type` selects the command variant on the Artemis side and `parameters` carries its payload. A concrete command subclasses `CommandDTO` and narrows `parameters` to a typed model, so an invalid payload fails in Iris rather than silently on the Artemis side.

`applied` is the whole result. It is `false` both when Artemis refused the command and when the client never carried it out.

## Transport

`StatusCallback.execute_command()` is the only way to send one. It derives the command URL from the callback URL it already holds — `…/runs/{runId}/status` becomes `…/runs/{runId}/command` — and authenticates with the run token as a bearer token, the same credential the status updates use. A callback URL without a `/status` suffix is treated as "not applied" rather than guessed at.

```python
result = callback.execute_command(PointOutCommandDTO(parameters=...))
if not result.applied:
    ...
```

The call is synchronous with a `COMMAND_TIMEOUT_SECONDS` budget of 10 seconds, and **every** failure mode — refused connection, read timeout, error status, unparseable body — is converted into `applied: false`. The pipeline never breaks or hangs over a command; the agent is told the view did not move and writes its answer accordingly.

:::note Two timeouts, deliberately ordered
Artemis waits for the browser's acknowledgement on a window that sits **below** this one. A command the client ignored therefore comes back as a valid `applied: false` response, not as a timeout here. Anything that does reach the exception handler means the call itself went wrong, which is why all of those are reported to Sentry.
:::

## The point-out command

```python
class PointOutCommandDTO(CommandDTO):
    type: str = "pointOut"
    parameters: PointOutParametersDTO
```

| Parameter         | Direction | Meaning                                                                                                                                                                 |
| ----------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lectureUnitId`   | both      | The unit to navigate in. Taken from the viewing context, never from the agent.                                                                                          |
| `page`            | both      | The slide's **index in the deck** — what Artemis navigates by.                                                                                                          |
| `timestamp`       | both      | Video time in seconds.                                                                                                                                                  |
| `displayPage`     | both      | The number printed on that slide. Sent only so Artemis can label the chat-history chip with the same number Iris names in its answer; navigation runs off `page` alone. |
| `lectureUnitName` | inbound   | Added by Artemis when it stores the marker. Only Artemis can resolve it.                                                                                                |

A `model_validator` rejects a command that names neither a page nor a timestamp. The same model is used in both directions, which is what keeps a stored marker parsing exactly like the command that produced it.

### The tool does not decide anything

`point_out_relevant_lecture_position` neither searches nor chooses. The agent retrieves lecture content first, picks a position from those results, and passes it in. The tool's job is to ground that position and report the outcome.

Grounding is the point of the tool. A model-invented page is a jump into an unrelated part of the deck, from the student's perspective for no reason at all:

| Request                                                                       | Resolution                                                                                                                                           |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `page` matches a retrieved page chunk of the viewed unit                      | Accepted. Its `display_page_number` becomes `displayPage`.                                                                                           |
| `page` matches a retrieved unit segment of the viewed unit                    | Accepted. Segments no longer advertise a point-out id, but their page is a real page of the unit, so rejecting it would only fail a legitimate call. |
| `page` matches only a transcription segment                                   | Rejected. A transcription's `page_number` is a printed number, not a deck index, and would resolve the wrong slide.                                  |
| `page` matches a result from another unit                                     | Rejected. Retrieval is not always scoped to the viewed unit, but the point-out always navigates inside it.                                           |
| `timestamp` falls inside a retrieved transcription segment of the viewed unit | Accepted. Intervals are half-open (`start <= t < end`), so a segment boundary belongs to the segment starting there.                                 |
| Neither given                                                                 | Rejected before anything else.                                                                                                                       |

### One command, two panes

`_resolve_slide()` and `_resolve_video()` each decide for their own pane without seeing the other, and the two answers are then assembled into one command. A slide worth showing is no reason to leave the video behind, and Artemis can only reconcile a page with a timestamp when they arrive together.

Both refusals are reported together as well. Returning on the first one would make an agent that got both wrong learn about them one retry at a time.

A pane also resolves to "stay put" when the student is already there. For the video that comparison carries a 0.5-second tolerance against the **requested moment itself**, not against the interval of the segment it was found in: retrieved intervals overlap and can span the whole lecture, so one covering both the student's position and the target says nothing about them being the same place.

### What the agent gets back

The return string is the agent's last input before it writes its answer, which is why each case says what the agent may claim:

| Outcome                                                     | Told to the agent                                                                                                          |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Moved                                                       | What was brought up, that this supersedes any earlier description of the student's position, and to refer to it naturally. |
| Already at that position                                    | The view was not moved; refer to it naturally anyway.                                                                      |
| Not applied (student left the view, or a transport failure) | The view could not be moved, and not to tell the student otherwise.                                                        |
| Rejected                                                    | Which value was not in the retrieved results.                                                                              |
| Another call after a successful move                        | Refused; further positions belong in the answer text.                                                                      |

One successful point-out per answer is enforced with a closure flag: jumping the view around mid-answer is confusing, and the restriction means the tool never has to track where an earlier point-out left the student. The flag is set **only** on the success path, so every other outcome leaves the allowance intact — a rejected target, an unapplied command, and a position the student was already at all let the agent correct its request and try again. `test_a_refused_point_out_does_not_use_up_the_answer_s_one_move` pins that. A single successful call naming a page _and_ a timestamp counts as the one point-out.

A successful call also invalidates the current-position snapshot — see [viewing context](./viewing-context.md#going-stale-mid-run).

### Point-out ids stay internal

The deck index is the only number the tool accepts and the only number the agent must never show the student. The tool's own success message names no page number for that reason: repeating one would invite the agent to copy it into its answer. [Printed slide numbers](./rag-pipeline.md#printed-slide-numbers) describes the two numberings.

## Command markers

An applied command is persisted by Artemis as a chat message with sender `COMMAND`, holding the executed command in the same `{type, parameters}` shape it was sent in. Every later request carries it in the chat history, so the agent knows where it took the student earlier in the conversation.

`convert_iris_message_to_langchain_message()` renders the marker as a `SystemMessage`, and `describe_command_marker()` builds the wording — next to the prompts, rather than in Artemis:

```text
Earlier in this conversation, Iris pointed the student to the slide on page 5
and the video at 56s of lecture unit 'Concurrency' (id 31) in the combined view.
```

Two rules govern that wording:

- **It is a record, never an instruction.** A marker says where the student was taken; it says nothing about whether they are still there. Phrasings like "already" imply the spot is dealt with and push the agent into skipping a point-out that is still the right move. Repeating one is free — the tool leaves the view untouched when the student has not moved — while skipping a needed one is not.
- **It names the printed page, never the deck index.** `describe_position()` omits the index deliberately: re-stating it in the history every turn from here on is the surest way to get it quoted eventually. Nothing is lost, since a fresh point-out takes its values from the retrieval results rather than from these notes.

A marker whose type has no case, or whose parameters do not validate, still yields a usable sentence. A marker must never be able to break a pipeline run over its wording.

## Adding a command type

1. Define the parameters model and a `CommandDTO` subclass under `domain/status/`, pinning `type` and narrowing `parameters`. Validate the payload there.
2. Send it from a tool through `callback.execute_command()`, and treat `applied: false` as a normal outcome the agent is told about.
3. Add a case to `describe_command_marker()` if Artemis persists a marker for it.
4. Implement the type in Artemis. An unimplemented type is dropped there immediately rather than forwarded, because no client could carry it out and waiting would stall the answer for nobody.
