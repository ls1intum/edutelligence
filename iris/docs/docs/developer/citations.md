---
title: Citations
---

# Citations

When an answer uses lecture or FAQ material, the chat agent cites it while it answers. The retrieval tools give every citable piece of content a **source id**, the agent writes `[src:N]` after each sentence that uses that content, and Pyris turns these markers into **cite blocks** when the answer is final. The Iris client in Artemis renders a cite block as a source chip the student can hover and click.

Only Pyris writes cite blocks, so a cite block in a message always comes from content a tool really returned in this run. The conversion runs inside `ChatPipeline.post_agent_hook()` (`_add_citations()`); see the [pipeline system](./pipeline-system.md) for where that hook sits.

## The citation format

A cite block is a bracketed block of colon-separated fields embedded in the answer text. This is what Iris returns to Artemis:

```text
[cite:<type>:<entity_id>:<page>:<start>:<end>:<keyword>:<summary>]
```

| Field       | Meaning                                                                            |
| ----------- | ---------------------------------------------------------------------------------- |
| `type`      | `L` for a lecture unit, `F` for an FAQ.                                            |
| `entity_id` | The lecture unit id or FAQ id.                                                     |
| `page`      | The slide's **index in the deck**, set only for a slide citation. Empty otherwise. |
| `start`     | A transcription segment's start time in whole seconds. Empty for a slide citation. |
| `end`       | That segment's end time in whole seconds. Empty for a slide citation.              |
| `keyword`   | The chip's short label (see [labels](#labels)).                                    |
| `summary`   | The one-to-two-sentence explanation shown in the marker's tooltip.                 |

A lecture citation is therefore either positioned on a slide (`page` set) or on a video moment (`start`/`end` set), never both: each citation points back at exactly one page chunk or one transcription segment. FAQ citations carry no position at all.

:::warning Three codebases share this format
The format is a contract between `citation_sources.py` in Iris, the Artemis server pattern in `IrisCitationService`, and the Artemis client pattern in `iris-citation-text.model.ts`. Artemis appends a further material-version field before it stores the answer, so the stored form has one field more than the one Iris emits. Change the format in all three places, or not at all.
:::

### Why `page` is the deck index

`page` is the slide's position in the PDF, which is what Artemis navigates by — not the number printed on the slide. The two differ for any deck with a title or agenda slide. The agent is told the opposite rule for its own answer text, where only the printed number may appear. See [printed slide numbers](./rag-pipeline.md#printed-slide-numbers) for how both numbers are stored and which is used where.

## Source ids

`ChatPipeline.prepare_state()` creates one `CitationSourceRegistry` per run (`state.citation_sources`), before the turn context and the tools are built. The registry hands out the ids:

- **What gets an id:** every slide chunk and transcription segment the lecture retrieval tool returns, every FAQ the FAQ retrieval tool returns, and the slide chunks and transcript segments of the student's current position (see [viewing context](./viewing-context.md)). Segment summaries and the agent's own knowledge get none.
- **How it is printed:** the tool writes a line `Source id: [src:N]` directly above the content (`source_id_line()`).
- **Stable ids:** the same piece of content always gets the same id within a run (by the chunk's or segment's uuid, by the FAQ id), also when the current view and a retrieval both return it. Ids are never reused, and a source from before a context switch stays citable.
- **Other pipelines:** a tool that gets no registry prints its output without ids, so pipelines without citations are unchanged.

The prompt block "Citing Sources" in `chat_system_prompt.j2` tells the agent the marker rules: copy ids exactly, one id per bracket, never inside code, no other citation format. It is rendered when the lecture or the FAQ tool is available.

### Only sources the model read

The chat registry is created with `require_delivery=True`. A source is registered when a tool formats it, which is before the tool output limit (`ToolOutputBudget`) may cut the result, and the current view registers its material before the tool that reads it out has run. So a source counts as **citable** only once its id line and its complete content were in a message the model received: `AbstractAgentPipeline` passes the text of every prompt message and every tool result (after output limits) to `observe_model_input()`, and `ChatPipeline` hands it to `CitationSourceRegistry.mark_delivered()`. The complete text the tool prints for the source must follow its id line directly: slide or transcript text in the frame `Content:\n---` … `---` (the lecture tool and the current view print it the same way, so a cut result cannot pass for another format), or the whole formatted FAQ. A result cut inside that text does not count, and text inside a source that looks like an id line does not matter.

## From markers to cite blocks

`CitationPipeline.__call__()` gets the answer and the registry:

1. **Collect what was cited.** `cited_source_ids()` reads the markers outside code and keeps the ids of citable sources, in order of first use.
2. **Label.** One LLM call writes a keyword and a summary for every cited source (see [labels](#labels)).
3. **Render.** `render_citations()` replaces each chain of markers with the cite blocks of its citable sources, repeats dropped. Markers of unknown or not citable sources and broken markers disappear. Cite blocks the agent wrote itself are removed everywhere, also inside code, because Artemis resolves every cite block it finds. Markers inside code stay untouched.

### Labels

`citation_label_prompt.txt` lists the cited sources as `Source N:` with the first 1,500 characters of their content (`MAX_EXCERPT_CHARS`; the beginning shows what a source is about, and the cap keeps the call short when an answer cites long transcript passages). The answer is schema-enforced (`CitationLabels`: a list of `source`, `keyword` and `summary`), with a `keyword` (the concept, 1–3 words) and a `summary` (what the source is about) per source. The summary is shown next to a tutoring answer, so it names the topics a source covers without stating results the student may still be working out; organizational facts such as dates may be stated. Keywords and summaries are written in the answer's language.

Providers enforce the schema while decoding (see [structured outputs](./pipeline-system.md#structured-outputs)); labels for sources that were not asked for are dropped. Output that does not match the schema gives no labels: the citations are still sent, with empty keyword and summary fields. `_sanitize_citation_field()` replaces `:`, `[` and `]` in every keyword and summary and collapses whitespace, because the fields are colon-delimited and bracket-terminated.

## Where markers are removed

The agent's markers are meant for the final answer only:

| Text                                                         | What happens                                                                                                                                                                                   |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Streamed drafts                                              | `citation_free_draft()` (the chat's `partial_text_transform()`) removes markers and cite blocks and holds back an end that may still grow into one. Cite blocks arrive with the final message. |
| Narration between tool calls                                 | `sanitize_narration()` removes them; Artemis stores this text as a message of its own.                                                                                                         |
| Earlier answers, the compaction summary and its cutoff quote | `sanitize_history_text()` removes cite blocks and markers before they go back to the agent, so it cannot copy old ids or blocks. The stored history keeps them.                                |
| Quiz JSON                                                    | `_strip_stray_citations()` removes markers and cite blocks from questions, options and explanations.                                                                                           |
| Exercise guide                                               | The guide keeps a marker next to the content it belongs to and removes it together with content it removes.                                                                                    |

The reply-language detection ignores markers, so a short answer with many ids is not mistaken for another language.

## Model roles

`CitationPipeline` resolves one role under the `citation_pipeline` id: `keyword_summary`, for the label call, always through the `default` variant. The call needs no reasoning; the example configuration uses a model entry with thinking turned off. `ChatPipeline` declares `Dep("citation_pipeline")`. Which model the role resolves to is deployment configuration — see the [variant system](./variant-system.md) and [LLM configuration](../admin/llm-configuration.md).

## Failure behavior

| Failure                         | Outcome                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------- |
| The label call fails or is cut  | Logged; the citations are sent without keyword and summary. Its usage is still billed.                   |
| Any other error while rendering | Logged in `ChatPipeline._add_citations()`; the answer is sent with all markers removed and no citations. |
