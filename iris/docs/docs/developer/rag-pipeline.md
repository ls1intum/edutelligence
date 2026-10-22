---
title: RAG Pipeline
---

# RAG Pipeline

Iris uses retrieval-augmented generation (RAG) to ground lecture and FAQ responses in course content. This page describes Iris's content collections and processing. It does not describe Memiris memory schemas, which are separate tenant-aware storage owned by the [Memiris library](https://github.com/ls1intum/edutelligence/tree/main/memiris).

Model roles, providers, and local/cloud selection belong in [LLM configuration](../admin/llm-configuration.md), the [variant system](./variant-system.md), and [developer configuration](./configuration.md), rather than this execution reference.

## Architecture overview

The RAG lifecycle has two separate phases:

```text
Ingestion: Artemis queue -> Iris ingestion worker (claim) -> Iris ingestion pipeline -> Iris Weaviate collections
Retrieval: user query -> rewrite/HyDE -> vector retrieval -> reranking -> agent tool result -> optional citations
```

Ingestion callbacks report processing state to Artemis. Retrieval classes are internal `SubPipeline` implementations: the owning chat or global-search-answer pipeline decides when to invoke them and owns the final callback.

## Iris content collections

`VectorDatabase` initializes five Iris-specific collections. They are distinct from Artemis Global Search and Memiris data.

| Collection              | Content                                                     |
| ----------------------- | ----------------------------------------------------------- |
| `Lectures`              | Page-level chunks extracted from lecture-unit PDF material. |
| `LectureTranscriptions` | Time-aware lecture transcription content.                   |
| `LectureUnitSegments`   | Segment-level slide/transcription material.                 |
| `LectureUnits`          | Lecture-unit metadata.                                      |
| `Faqs`                  | Course FAQ question-and-answer content.                     |

The collections retain course and lecture/unit metadata so ingestion, deletion, and retrieval can remain scoped to the requested content.

## Ingestion and deletion

### Lecture PDFs

`LectureIngestionUpdatePipeline` coordinates the lecture-unit update flow. The PDF ingestion path extracts lecture-page content, processes relevant visual material, chunks text, vectorizes it, and writes `Lectures` records with their metadata. It also updates the related lecture-unit representation used by retrieval. A lecture-unit job, whether the ingestion worker claimed it or a caller pushed it through the webhook, runs on a thread registered in `IngestionJobHandler`, which starts it immediately and supersedes any run still in progress for the same base URL, course, lecture, and lecture unit. See [ingestion jobs](./ingestion-jobs.md) for the supersession and cancellation contract.

For an updated attachment, `LectureUnitPageIngestionPipeline` performs the following source-backed sequence:

1. decode the base64 PDF into a temporary file and open it with PyMuPDF;
2. extract page text and render relevant page imagery;
3. interpret visual content and merge it with the extracted text where applicable;
4. split the merged page content into chunks while retaining course, lecture, lecture-unit, page, URL, and attachment-version metadata;
5. generate embeddings and batch-write the chunks to `Lectures`; and
6. remove the temporary file and report token/status updates through the ingestion callback.

If the stored attachment version is already current, the pipeline can retain the existing chunks and restore display-page metadata instead of re-ingesting the PDF. Updated content is written as a new generation first and the previous rows are purged only once it is verified, so an interrupted run never leaves the unit empty; see [Ingestion reliability](./ingestion-reliability.md#writing-a-generation).

### Printed slide numbers

A slide has two numbers, and keeping them apart is a cross-cutting constraint rather than an ingestion detail:

| Number                          | Stored as             | Role                                                                                                            |
| ------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------- |
| The slide's index in the deck   | `page_number`         | What Artemis navigates by — a citation's position and a point-out target. Internal; never shown to the student. |
| The number printed on the slide | `display_page_number` | What the student sees on the slide. The only page number the agent may name in an answer.                       |

They diverge for any deck with a title or agenda slide before printed page 1, which is most of them.

The printed number is read during ingestion. `interpret_image()` returns a `SlideVisionDTO` per page carrying the `academic_description` that is merged into the page text and the `display_page_number` visible on the slide, or `-1` when none is legible. Because vision reads each slide in isolation, a number can come back missing or simply wrong — a figure label or a "Lecture 6" footer read as the page number.

`_reconcile_display_page_numbers()` turns those independent reads into one consistent sequence:

1. **A dominant offset wins.** Printed numbers almost always track the physical index by a constant offset. When a strict majority of the legible reads agree on one offset, every page is snapped to it. That single step both fills the `-1` gaps and overrides the minority of misreads. Front-matter pages that snap to zero or below carry no printed number and are recorded as `-1`.
2. **Otherwise, gaps are interpolated.** With no majority — irregular or restarting numbering — the confident reads are trusted and only the `-1` gaps are filled from their nearest read neighbours.
3. **With nothing legible at all**, the sequential page number is used.

The reconciled list is written onto every page chunk and the matching unit segments, and is reported to Artemis as `displayPageNumbers` on the terminal ingestion status update, so both services describe a slide by the same number.

`printed_page_number()` in `domain/retrieval/lecture/lecture_retrieval_dto.py` is the single normalizer: it maps `-1`, legacy `0`, and `None` to `None`, meaning "no printed number". Everything that shows a page to the agent or to Artemis goes through it — the retrieval tool's output, the student's current position, the point-out parameters — so a slide is never described by a nonsensical number and the three can never disagree about which slides count as unnumbered.

Retrieval results make the distinction explicit. A page chunk is rendered as `Page: N, point-out id: M`, a transcription segment as `Page: N` only (its `page_number` is the printed number read off the video frame, not a deck index), and a unit segment as `Page: N` with no handle of its own. The prompt instructs the agent accordingly: quote `Page`, pass `point-out id`, and never the other way round. See [client commands](./client-commands.md) and [viewing context](./viewing-context.md).

### Transcriptions and segments

`TranscriptionIngestionPipeline` receives transcription input and stores transcription records. Lecture-unit segment processing combines the relevant slide and transcription material into `LectureUnitSegments`, retaining scalar source identifiers and page metadata. Cross-collection Weaviate reference creation is currently disabled. Transcription support includes the Iris transcription helpers for audio/video processing and alignment; the exact provider or model is configuration-dependent unless source code makes it an implementation constraint.

The unified update pipeline can generate a missing transcription, resume from a raw transcription, or ingest an already enriched transcription. It checkpoints raw and slide-aligned transcription data through the callback so Artemis can retain progress for retries, then ingests the resulting transcription and computes the lecture-unit summaries. Transcription-generation failures and later vector/PDF/summary failures are reported as distinct failure categories.

### FAQs and deletes

`FaqIngestionPipeline` writes the FAQ representation to `Faqs` and can remove it by FAQ and course identity. FAQ ingestion/deletion, as well as lecture deletion, start raw worker threads directly; they are not deduplicated by `IngestionJobHandler`. `LectureUnitDeletionPipeline` removes stored lecture-unit data and reports its outcome through the deletion callback.

## Lecture retrieval

`LectureRetrieval` is an internal `SubPipeline` used by relevant Iris agents. It assembles a `LectureRetrievalDTO` through these stages:

1. resolve lecture-unit context and detect whether matching transcription data exists;
2. produce page-oriented and, when applicable, transcription-oriented rewritten queries and hypothetical answers in parallel;
3. embed each distinct generated query once and reuse those vectors across the compatible retrieval stages;
4. retrieve page chunks, transcriptions, and lecture-unit segments in parallel;
5. fetch surrounding page/transcription content for matching segments and remove duplicates;
6. rerank applicable page and transcription results; and
7. assemble the typed `LectureRetrievalDTO` for the calling tool or agent.

Because query embeddings are reused, the lecture, segment, and transcription retrieval configurations must resolve to the same embedding model. `LectureRetrieval` validates that invariant at construction instead of silently searching incompatible vector spaces.

The parallel sources have different roles:

| Retriever                       | Collection              | Result                          |
| ------------------------------- | ----------------------- | ------------------------------- |
| `LecturePageChunkRetrieval`     | `Lectures`              | Page chunks and page context.   |
| `LectureTranscriptionRetrieval` | `LectureTranscriptions` | Matching transcription content. |
| `LectureUnitSegmentRetrieval`   | `LectureUnitSegments`   | Combined segment material.      |

Retrieval requests carry course, lecture, lecture-unit, and Artemis-instance scope. On the current default branch, individual retrievers apply a subset of that scope rather than consistently composing every supplied identifier; callers must not treat lecture-unit isolation as guaranteed until the corresponding retrieval-filter change is merged. Reranking is an Iris stage over the applicable retrieved results; its configured provider and model must not be inferred from this page.

## FAQ retrieval and citations

`FaqRetrieval` searches the `Faqs` collection for a course-scoped FAQ context. Chat modes and tools decide whether FAQ retrieval is available for a particular request.

After a response uses lecture or FAQ material, the nested citation pipeline can generate source attribution for the parent response. Citation generation is post-processing inside the parent pipeline, not an independently callable Artemis endpoint. The marker format, the keyword/summary enrichment, and what the citations are built from are documented in [citations](./citations.md).

## Vector database lifecycle

`VectorDatabase` owns the shared Iris Weaviate client. It creates the configured connection under a process-level lock, registers client cleanup, and initializes the five Iris collections once per process. Later `VectorDatabase` instances reuse both the client and collection handles. Individual schema initializers return existing collections when present, so service startup establishes the collection contract without recreating it for each request.

## Boundaries

- **Artemis Global Search** has its own authorization model and schemas. Iris's global-search answer path may retrieve lecture content, but it does not merge the two storage systems; see [Global search](./global-search.md).
- **Ingestion reliability**, meaning how a run writes, verifies and reports a unit, is described in [Ingestion reliability](./ingestion-reliability.md).
- **Memiris** uses separate learning, memory, and relationship schemas. Iris's wrapper, memory tools, and periodic sleep scheduling are documented in the [pipeline system](./pipeline-system.md); reusable library internals live in the Memiris README.
