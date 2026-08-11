---
title: RAG Pipeline
---

# RAG Pipeline

Iris uses retrieval-augmented generation (RAG) to ground lecture and FAQ responses in course content. This page describes Iris's content collections and processing. It does not describe Memiris memory schemas, which are separate tenant-aware storage owned by the [Memiris library](https://github.com/ls1intum/edutelligence/tree/main/memiris).

Model roles, providers, and local/cloud selection belong in [LLM configuration](../admin/llm-configuration.md), the [variant system](./variant-system.md), and [developer configuration](./configuration.md), rather than this execution reference.

## Architecture overview

The RAG lifecycle has two separate phases:

```text
Ingestion: Artemis webhook -> Iris ingestion pipeline -> Iris Weaviate collections
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

`LectureIngestionUpdatePipeline` coordinates the lecture-unit update flow. The PDF ingestion path extracts lecture-page content, processes relevant visual material, chunks text, vectorizes it, and writes `Lectures` records with their metadata. It also updates the related lecture-unit representation used by retrieval. The incoming lecture-unit webhook runs on a thread through `IngestionJobHandler`; its duplicate-job suppression is only for the same course, lecture, and lecture-unit identity.

For an updated attachment, `LectureUnitPageIngestionPipeline` performs the following source-backed sequence:

1. decode the base64 PDF into a temporary file and open it with PyMuPDF;
2. extract page text and render relevant page imagery;
3. interpret visual content and merge it with the extracted text where applicable;
4. split the merged page content into chunks while retaining course, lecture, lecture-unit, page, URL, and attachment-version metadata;
5. generate embeddings and batch-write the chunks to `Lectures`; and
6. remove the temporary file and report token/status updates through the ingestion callback.

If the stored attachment version is already current, the pipeline can retain the existing chunks and restore display-page metadata instead of re-ingesting the PDF. Updated content is scoped and replaced before the new chunks are written.

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

After a response uses lecture or FAQ material, the nested citation pipeline can generate source attribution for the parent response. Citation generation is post-processing inside the parent pipeline, not an independently callable Artemis endpoint.

## Vector database lifecycle

`VectorDatabase` owns the shared Iris Weaviate client. It creates the configured connection under a process-level lock, registers client cleanup, and initializes the five Iris collections once per process. Later `VectorDatabase` instances reuse both the client and collection handles. Individual schema initializers return existing collections when present, so service startup establishes the collection contract without recreating it for each request.

## Boundaries

- **Artemis Global Search** has its own authorization model and schemas. Iris's global-search answer path may retrieve lecture content, but it does not merge the two storage systems.
- **Memiris** uses separate learning, memory, and relationship schemas. Iris's wrapper, memory tools, and periodic sleep scheduling are documented in the [pipeline system](./pipeline-system.md); reusable library internals live in the Memiris README.
