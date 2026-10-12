---
title: Viewing Context
---

# Viewing Context

A chat request can carry **where the student is looking** while they ask: which slide page is on screen, how far into the recording they are, or both at once in the combined view. Iris uses it to narrow retrieval to that lecture unit and to let the agent read out the material the student actually has in front of them, so a question like "what does this mean?" can be answered without the student naming the page.

This is separate from the chat's active context. The active context is the lecture or exercise the chat is about and is stored on the session; the viewing context describes one moment and arrives with one message. See [chat context switching](./pipeline-system.md#context-switching) for the former.

## The `context` field

`ChatPipelineExecutionDTO.context` is an optional list of position objects. Artemis sends it on a lecture chat request and sends nothing when the student has interacted with neither the slides nor the video.

```python
context: Optional[List[LectureContextDTO]] = None
```

`LectureContextDTO` is a union of three shapes, discriminated by `type`:

| `type`         | Fields                              | Meaning                                                               |
| -------------- | ----------------------------------- | --------------------------------------------------------------------- |
| `slides`       | `lectureUnitId`, `page`             | A PDF page is on screen. Pages start at 1.                            |
| `video`        | `lectureUnitId`, `timestamp`        | The player stands at `timestamp` seconds.                             |
| `combinedView` | optional `slides`, optional `video` | One unit is open in the combined view, with Iris beside the material. |

A `combinedView` entry nests the other two rather than repeating their fields, because that view always shows exactly one unit. Its `lecture_unit_id` is therefore a derived property: it prefers `slides.lecture_unit_id` and falls back to `video.lecture_unit_id`, and returns `None` only when neither nested object is present.

`ChatPipelineExecutionDTO` has a `model_validator` that copies that derived id into `lecture_unit_id` when the field is not already set, which is what scopes RAG retrieval to the unit. An explicitly sent `lecture_unit_id` always wins.

:::note Nothing here is persisted
Artemis attaches the context to the outgoing request and discards it. A reloaded conversation shows its messages without it. Treat it as a retrieval filter for one message, not as part of the stored session — anything a later reader of the history must see has to be in a message, which is what a [command marker](./client-commands.md#command-markers) is for.
:::

## What Iris does with it

`ChatPipeline.prepare_state()` parses the array onto `state.lecture_contexts`, and `_build_current_view()` resolves it once per run, before the tools are built.

The result is deliberately split in two. The agent is **told where the student is** on every turn, and may **ask what is there** when it decides it needs to:

| What                                                   | How the agent gets it                                     | When                                             |
| ------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------ |
| The position — page number, video timestamp, unit      | Pushed, as a block in the per-turn system message         | Every turn that carries a usable viewing context |
| The material at that position — slide text, transcript | Pulled, through the `read_students_current_position` tool | Only when the agent calls that tool              |
| The lecture unit as a retrieval scope                  | Applied inside the lecture retrieval tool                 | Whenever the agent retrieves                     |

So an agent that never calls the tool still knows the student is on page 4 of a named unit — it just does not know what page 4 says. That is the intended state: the position is cheap and frames the question, while the material is only worth spending context on when the question is actually about what is on screen.

### 1. Retrieval scope

The derived `lecture_unit_id` narrows the lecture retrieval tool to the unit the student is viewing, through the same scope plumbing a context switch uses. See the [RAG pipeline](./rag-pipeline.md#lecture-retrieval).

### 2. The position, pushed every turn

`_build_current_view()` produces two parallel renderings of the same positions: the bare position, which goes into the prompt, and the position together with its material, which goes to the tool. The bare one reads:

```text
The student is currently viewing page 4 of the lecture slides of the lecture unit
Concurrency (lecture unit ID: 31).
```

`_collect_context_positions()` flattens the array into a page list and a timestamp list first, unnesting `combinedView` into its two parts, so the three context types collapse into two lookups. `LectureRetrieval.fetch_context_content()` then looks the positions up directly — by page number and by covering time interval — rather than searching. It is not RAG: the student's position is a known coordinate, and a vector query could return a different slide for it.

Two filters decide whether a position is mentioned at all:

- **Unreleased units are skipped.** `_is_lecture_unit_released()` checks the stored lecture-unit record, memoized per request, so a position in a unit the student should not see yields nothing.
- **Positions without ingested material are dropped.** If neither page chunks nor transcription segments come back, the position is left out entirely. Listing a position Iris has no content for would only invite the agent to bluff about a page it cannot read.

A position that survives both is rendered into `chat_turn_context.j2` and sent as a system message **after** the chat history, rather than into `chat_system_prompt.j2`. The system prompt is the start of the cached prefix and has to stay identical across the turns of a session, while the position changes with every message. See [prompts](./prompts.md#the-students-current-position).

A slide position is labelled by the number **printed on the slide**, via `_current_slide_label()`. The agent is told throughout to quote printed numbers and never deck indices, and describing its position by the index would hand it a wrong number to quote. See [printed slide numbers](./rag-pipeline.md#printed-slide-numbers).

### 3. The material, only on request

The prompt names the position but never reproduces what is on it. The material goes to `state.current_view_storage` instead, and reaches the model only if it calls `read_students_current_position`.

This split is the point of the design, not an optimization. Spelling the slide text out in the prompt ends the prompt with something that reads like a finished answer, and a weaker model then answers from it instead of reaching for any tool at all — including the retrieval and point-out tools the question actually needed. Behind a tool the same material stays available, but the model has to decide it wants it.

The tool's docstring states plainly that this is not a search: it returns the one position the student happens to be at, which may have nothing to do with their question, and carries no point-out id, so its result cannot be passed to the point-out tool.

`provide_current_view_content()` withholds the tool when the storage holds no blocks, and also when the lecture tool is not allowed for the request — a viewing context must not become a way around that gate. The turn-context template checks `allow_lecture_tool` separately before naming the tool in its instructions, because the position lines are built from the vector database directly and survive a withheld tool. A student's position can therefore be stated without any tool existing to read it out.

### Citations without a tool call

`_build_current_view()` also stores its content under `lecture_content_storage["current_view"]`. The citation pipeline merges that with whatever the retrieval tool retrieved, so an answer about the open slide carries a source chip even if the agent never retrieved anything. See [citations](./citations.md#what-gets-cited).

## Going stale mid-run

The position blocks are a snapshot of where the student stood when the run started, and the system prompt cannot be re-rendered mid-run. The [point-out command](./client-commands.md) can move the student during the same run, which invalidates that snapshot.

The point-out tool therefore writes `MOVED_AWAY_KEY` into `current_view_storage`, and `read_students_current_position` checks it on **every** call rather than capturing the blocks when the tool was built. Once set, the tool stops handing out the blocks and says so. The invalidation is wholesale even when only the slides moved: every block is labelled as what the student sees "right now", and one stale block next to a still-valid one is exactly the mix that produces an answer about the wrong view.

## The combined view

A `combinedView` entry is also what unlocks the point-out tool, because that is the only view whose material Artemis can move. `get_combined_view_context()` is the single place that decides whether a usable combined-view context is present — it requires a resolvable `lecture_unit_id` — and both `provide_combined_view_point_out()` and the `can_point_out_in_combined_view` prompt flag derive from it, so the prompt cannot advertise a tool that was never registered.

## Adding a context type

1. Add the DTO in `domain/data/lecture_context_dto.py` with its `type` literal and add it to the `LectureContextDTO` union. Artemis must emit the same discriminator.
2. Handle it in `ChatPipeline._collect_context_positions()`, either by mapping it onto an existing page/timestamp lookup or by adding a third one.
3. Add the lookup to `LectureRetrieval.fetch_context_content()` if it needs one, keeping the release check.
4. Render its position line in `_build_current_view()`, in the terms the student sees it.
