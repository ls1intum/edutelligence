---
title: Citations
---

# Citations

When an answer uses lecture or FAQ material, `CitationPipeline` inserts citation markers into the answer text. A marker names the source it supports, and the Iris client in Artemis renders it as a source chip the student can hover and click.

Citations are **post-processing inside the parent pipeline**, not a separately callable route. `ChatPipeline.post_agent_hook()` invokes the pipeline after the agent has written its answer; see the [pipeline system](./pipeline-system.md) for where that hook sits.

## The citation format

A citation is a bracketed block of colon-separated fields embedded in the answer text. It exists in two forms, and both are produced inside one pipeline run.

**Intermediate form** — what the citation model is given and what it writes back:

```text
[cite:<type>:<entity_id>:<page>:<start>:<end>!<sequence>]
```

**Final form** — what Iris returns to Artemis:

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
| `keyword`   | The chip's short label, generated per citation.                                    |
| `summary`   | The one-to-two-sentence explanation shown in the chip's tooltip.                   |

A lecture citation is therefore either positioned on a slide (`page` set) or on a video moment (`start`/`end` set), never both: each citation points back at exactly one retrieved page chunk or one transcription segment. FAQ citations carry no position at all.

:::warning Three codebases share this format
The format is a contract between the Iris citation pipeline, the Artemis server pattern in `IrisCitationService`, and the Artemis client pattern in `iris-citation-text.model.ts`. Artemis appends a further material-version field before it stores the answer, so the stored form has one field more than the one Iris emits. Change the format in all three places, or not at all.
:::

### Why `page` is the deck index

`page` is the slide's position in the PDF, which is what Artemis navigates by — not the number printed on the slide. The two differ for any deck with a title or agenda slide. The agent is told the opposite rule for its own answer text, where only the printed number may appear. See [printed slide numbers](./rag-pipeline.md#printed-slide-numbers) for how both numbers are stored and which is used where.

## The two phases of a run

`CitationPipeline.__call__()` runs an LLM call to place the citations, then a second stage to fill in their labels.

1. **Serialize the sources.** `create_formatted_lecture_string()` (or `create_formatted_faq_string()` for FAQs) renders the retrieved content as a JSON array of `{"id", "content"}` entries. Each `id` is a complete intermediate-form citation, and each one gets the next **sequence number** after the `!`.
2. **Place the citations.** `citation_prompt.txt` instructs the model to copy ids verbatim behind the sentences they support, and to change nothing else about the answer. It is told to return the answer unchanged when no provided content was used.
3. **Collect what was used.** `extract_used_citation_numbers()` reads the sequence numbers out of the model's output. Only those sources get enriched, so an answer citing two of twenty retrieved paragraphs costs two enrichments.
4. **Enrich.** `_build_keyword_summary_map()` generates one keyword and one summary per used sequence number.
5. **Rewrite.** `_replace_cite_blocks_with_keyword_summary()` substitutes every intermediate block with its final form, dropping the sequence number and appending the keyword and summary.

### What the sequence number is for

The sequence number is the only link between a citation in the answer and the source text it came from. `create_formatted_lecture_string()` stores that text in `_last_citation_content_by_seq` under the same number, which is what the keyword and summary stages read. The id fields alone could not serve: two page chunks of the same slide carry identical `type`, `entity_id` and `page`, so they would be indistinguishable.

It never reaches Artemis. Phase 5 replaces it with the keyword and summary generated for it.

### Keywords are sequential, summaries are parallel

`_build_keyword_summary_map()` runs both stages in one thread pool, but they are shaped differently:

| Stage     | Execution                               | Why                                                                                                                                                                                           |
| --------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Keywords  | One task, looping over the citations    | `citation_keyword_prompt.txt` takes the keywords already used as `{UsedKeywords}` and is told not to reuse them. Deduplication requires the earlier results, so the calls cannot be parallel. |
| Summaries | One task per citation, run concurrently | `citation_summary_prompt.txt` sees only its own paragraph, so nothing orders the calls.                                                                                                       |

Each task builds its own `IrisLangchainChatModel` over the shared request handler, because one model instance accumulates token usage and would be written to from several threads at once. Token appends are taken under `_tokens_lock` for the same reason.

### Field sanitization

`_sanitize_citation_field()` replaces `:`, `[` and `]` in every generated keyword and summary and collapses whitespace. The fields are colon-delimited and bracket-terminated, so an unescaped colon in a keyword would shift every field behind it. The summary is the last field and is therefore the one place a parser can tolerate extra colons — Artemis reads it as everything up to the closing bracket — but it is sanitized as well rather than relying on being last.

## Model roles

`CitationPipeline` resolves two separate model roles under the `citation_pipeline` id:

| Role              | Used for                                            |
| ----------------- | --------------------------------------------------- |
| `chat`            | Placing the citations into the answer.              |
| `keyword_summary` | Generating each cited source's keyword and summary. |

Two roles rather than one because the two calls have different shapes: placement is a single call over the whole answer and every retrieved source, enrichment is many small calls over one paragraph each. Splitting them lets a deployment put the enrichment calls on a cheaper model without touching the placement call.

Which model each role resolves to is deployment configuration — see [LLM configuration](../admin/llm-configuration.md). The pipeline itself offers a `default` and an `advanced` variant for the `chat` role, and `ChatPipeline` declares `Dep("citation_pipeline", variant="same")`, so the chat variant selects the citation variant too. See the [variant system](./variant-system.md).

## What gets cited

`ChatPipeline._add_citations()` runs the pipeline up to twice per answer — once over the FAQ storage, once over the lecture content — and each run only rewrites the answer it is given.

The lecture run cites the union of two sources, merged by `_merge_lecture_content()` and de-duplicated by uuid:

- **What the lecture retrieval tool retrieved**, under `lecture_content_storage["content"]`.
- **The material at the student's current position**, under `lecture_content_storage["current_view"]`, stored before the agent ran. This is what makes an answer about the open slide carry a citation even when the agent never called the retrieval tool. See [viewing context](./viewing-context.md).

De-duplication matters because the current slide is frequently also returned by RAG, and the same paragraph cited twice becomes two chips on one sentence.

The current view is dropped when the agent switched the chat context during the run: the answer is then about the target lecture, and the position the student still has open belongs to the previous one.

## Failure behavior

Failures are handled at different points:

| Failure                                                | Outcome                                                                                                                                                                                |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A summary call or the sequential keyword task          | Logged; rewriting continues. A failed summary leaves that summary empty; a failed keyword task can leave all keywords empty.                                                           |
| An unexpected error in the enrichment or rewrite stage | Logged; `CitationPipeline` returns the placement result without rewriting its intermediate `!sequence` markers. Those markers are not guaranteed to render as source chips.            |
| Citation placement                                     | Raised out of `CitationPipeline` and caught by `ChatPipeline._add_citations()`. The current answer text is returned; if the FAQ citation pass already succeeded, its citations remain. |

These paths preserve the answer text, but an unexpected enrichment error can leave citations in a form the client cannot use.

## Language

`user_language` prepends a one-line instruction to every prompt in the run, so the keyword and summary of a chip are written in the student's language rather than in the language of the slide.
