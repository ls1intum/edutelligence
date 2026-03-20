---
title: RAG Pipeline
---

# RAG Pipeline

Iris uses Retrieval-Augmented Generation (RAG) to ground LLM responses in actual course content. This page covers the ingestion and retrieval pipelines that power lecture and FAQ content lookup.

## Architecture Overview

The RAG system has two phases:

1. **Ingestion** — Course content (lecture PDFs, transcriptions, FAQs) is processed, chunked, and stored as vectors in Weaviate.
2. **Retrieval** — At query time, the student's question is used to find relevant content, which is then provided to the LLM agent as tool output.

```
Ingestion Phase:
  Artemis → Iris API → Ingestion Pipeline → Weaviate

Retrieval Phase:
  Student Query → Query Rewriting → Vector Search → Reranking → Agent Context
```

## Weaviate Collections

The vector database stores content in five collections, each defined as a schema in `src/iris/vector_database/`:

| Collection              | Schema File                         | Content                                           |
| ----------------------- | ----------------------------------- | ------------------------------------------------- |
| `Lectures`              | `lecture_unit_page_chunk_schema.py` | Chunked text from lecture PDF pages               |
| `LectureTranscriptions` | `lecture_transcription_schema.py`   | Lecture video/audio transcriptions                |
| `LectureUnitSegments`   | `lecture_unit_segment_schema.py`    | Summaries combining slide + transcription content |
| `LectureUnits`          | `lecture_unit_schema.py`            | Lecture unit metadata                             |
| `FAQs`                  | `faq_schema.py`                     | FAQ question-answer pairs                         |

Each collection stores:

- **Vector embeddings** — Generated using an embedding model (e.g., `text-embedding-3-small`).
- **Text content** — The original text for display in responses.
- **Metadata** — Course ID, lecture ID, page numbers, etc., used for filtering.

### Schema Example

From `lecture_unit_page_chunk_schema.py`:

```python
class LectureUnitPageChunkSchema(Enum):
    COLLECTION_NAME = "Lectures"
    COURSE_ID = "course_id"
    COURSE_LANGUAGE = "course_language"
    LECTURE_ID = "lecture_id"
    LECTURE_UNIT_ID = "lecture_unit_id"
    PAGE_TEXT_CONTENT = "page_text_content"
    PAGE_NUMBER = "page_number"
    BASE_URL = "base_url"
    PAGE_VERSION = "attachment_version"
```

## Ingestion Pipelines

### Lecture PDF Ingestion

**Pipeline:** `LectureUnitPageIngestionPipeline` (`src/iris/pipeline/lecture_ingestion_pipeline.py`)

This is the most complex ingestion pipeline. The flow is:

1. **Receive PDF** — Artemis sends a base64-encoded PDF via the webhook API.
2. **Save to temp file** — The PDF is decoded and saved to a temporary file.
3. **Extract pages** — [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) extracts text and images from each page.
4. **Image interpretation** — If pages contain images, an LLM interprets the image content and merges it with the text.
5. **Text chunking** — `RecursiveCharacterTextSplitter` from LangChain breaks large pages into smaller chunks.
6. **Generate embeddings** — Each chunk is embedded using the configured embedding model.
7. **Store in Weaviate** — Chunks are batch-inserted into the `Lectures` collection with metadata.
8. **Cleanup** — The temporary PDF file is deleted.

The ingestion runs in a **separate process** managed by `IngestionJobHandler`. If the same lecture unit is re-ingested, the handler terminates the old process first:

```python
class IngestionJobHandler:
    def add_job(self, process, course_id, lecture_id, lecture_unit_id):
        # If a job already exists for this lecture unit, terminate it
        old_process = self.job_list.get(course_id, {}).get(lecture_id, {}).get(lecture_unit_id)
        if old_process:
            old_process.terminate()
            old_process.join()
        # Start the new process
        process.start()
```

### Transcription Ingestion

**Pipeline:** `TranscriptionIngestionPipeline` (`src/iris/pipeline/transcription_ingestion_pipeline.py`)

Processes lecture video/audio transcriptions:

1. Receives transcription text from Artemis.
2. Segments and chunks the transcription.
3. Generates embeddings and stores in the `LectureTranscriptions` collection.

### FAQ Ingestion

**Pipeline:** `FaqIngestionPipeline` (`src/iris/pipeline/faq_ingestion_pipeline.py`)

Ingests FAQ entries:

1. Receives FAQ question-answer pairs from Artemis.
2. Embeds the combined question + answer text.
3. Stores in the `FAQs` collection.

### Lecture Update Ingestion

**Pipeline:** `LectureIngestionUpdatePipeline` (`src/iris/pipeline/lecture_ingestion_update_pipeline.py`)

Handles updates to already-ingested lectures:

1. Deletes existing chunks for the lecture unit.
2. Re-runs the full ingestion pipeline with the updated content.

### Lecture Unit Deletion

**Pipeline:** `LectureUnitDeletionPipeline` (`src/iris/pipeline/delete_lecture_units_pipeline.py`)

Removes all stored vectors for deleted lecture units.

## Retrieval Pipeline

### Lecture Content Retrieval

**Location:** `src/iris/retrieval/lecture/lecture_retrieval.py`

The `LectureRetrieval` class is a `SubPipeline` that orchestrates multi-source retrieval:

```python
class LectureRetrieval(SubPipeline):
    def __call__(self, query, course_id, chat_history, ...) -> LectureRetrievalDTO:
        # 1. Get lecture unit metadata
        lecture_unit = self.get_lecture_unit(course_id, lecture_id, lecture_unit_id)

        # 2. Rewrite the student query for better retrieval
        rewritten_query = self.rewrite_query(query, chat_history)

        # 3. Retrieve from three sources in parallel
        #    - Lecture page chunks
        #    - Lecture transcriptions
        #    - Lecture unit segments

        # 4. Rerank results using Cohere
        reranked_results = self.cohere_client.rerank(...)

        # 5. Return combined results as LectureRetrievalDTO
```

The retrieval process has several stages:

#### 1. Query Rewriting

The student's query is rewritten by an LLM to be better suited for vector search. This uses prompts from `lecture_retrieval_prompts.py`:

- **Standard rewriting** — Reformulates the question for semantic search.
- **Hypothetical answer generation** — Generates a hypothetical answer that would appear in the lecture content (HyDE technique).

#### 2. Multi-source Retrieval

Three sub-retrievers run in parallel using `TracedThreadPoolExecutor`:

| Retriever                       | Collection            | Returns                                |
| ------------------------------- | --------------------- | -------------------------------------- |
| `LecturePageChunkRetrieval`     | Lectures              | Page text chunks with page numbers     |
| `LectureTranscriptionRetrieval` | LectureTranscriptions | Transcription segments                 |
| `LectureUnitSegmentRetrieval`   | LectureUnitSegments   | Combined slide+transcription summaries |

Each retriever performs vector similarity search filtered by `course_id` (and optionally `lecture_id` / `lecture_unit_id`).

#### 3. Reranking

Retrieved page chunks and transcriptions are reranked using **Cohere's reranker** (`rerank-multilingual-v3.5`) to improve relevance ordering. Lecture unit segments are retrieved separately and are not reranked. The reranker is configured in `llm_config.yml`:

```yaml
- id: cohere
  name: Cohere Client V2
  type: cohere_azure
  model: "rerank-multilingual-v3.5"
  endpoint: "your_cohere-endpoint"
  api_key: "..."
```

#### 4. Result Assembly

Results are assembled into a `LectureRetrievalDTO`:

```python
@dataclass
class LectureRetrievalDTO:
    lecture_unit_page_chunks: list[LectureUnitPageChunkRetrievalDTO]
    lecture_transcriptions: list[LectureTranscriptionRetrievalDTO]
    lecture_unit_segments: list[LectureUnitSegmentRetrievalDTO]
```

### FAQ Retrieval

**Location:** `src/iris/retrieval/faq_retrieval.py`

Similar to lecture retrieval but queries the `FAQs` collection. Used by the course chat and exercise chat pipelines when FAQ content is available.

## Citation Generation

After the agent produces a response using retrieved content, the `CitationPipeline` (`src/iris/pipeline/shared/citation_pipeline.py`) generates citations that link back to specific lecture slides or pages. This runs as a post-processing step to provide source attribution.

## The VectorDatabase Class

**Location:** `src/iris/vector_database/database.py`

The `VectorDatabase` class manages the Weaviate connection as a singleton:

```python
class VectorDatabase:
    _lock = threading.Lock()
    static_client_instance = None

    def __init__(self):
        with VectorDatabase._lock:
            if not VectorDatabase.static_client_instance:
                VectorDatabase.static_client_instance = weaviate.connect_to_local(
                    host=settings.weaviate.host,
                    port=settings.weaviate.port,
                    grpc_port=settings.weaviate.grpc_port,
                )
        self.client = VectorDatabase.static_client_instance
        self.lectures = init_lecture_unit_page_chunk_schema(self.client)
        self.transcriptions = init_lecture_transcription_schema(self.client)
        self.lecture_segments = init_lecture_unit_segment_schema(self.client)
        self.lecture_units = init_lecture_unit_schema(self.client)
        self.faqs = init_faq_schema(self.client)
```

Collections are lazily initialized — schemas are created in Weaviate if they do not already exist.
