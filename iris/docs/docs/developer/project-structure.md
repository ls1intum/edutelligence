---
title: Project Structure
---

# Project Structure

This page documents the directory layout of the Iris codebase and explains the purpose of each major component.

## Top-level Layout

```
iris/
├── src/iris/                  # Main application source code
├── tests/                     # Test suite
├── docs/                      # Documentation site (Docusaurus)
├── docker/                    # Docker Compose files (Weaviate, dev, production, Nginx)
├── application.example.yml    # Example application configuration
├── llm_config.example.yml     # Example LLM configuration
├── pyproject.toml             # Poetry project definition and dependencies
└── README.MD                  # Project README
```

## Source Code (`src/iris/`)

The main application code lives under `src/iris/`. Here is the breakdown:

```
src/iris/
├── main.py                    # FastAPI application entry point
├── config.py                  # Configuration loading (Settings class)
├── sentry.py                  # Sentry error tracking initialization
├── dependencies.py            # FastAPI dependency injection (token validation)
├── common/                    # Shared utilities
├── domain/                    # Data Transfer Objects and domain models
├── pipeline/                  # Pipeline system (core business logic)
├── tools/                     # LLM-callable tools
├── llm/                       # LLM client implementations
├── retrieval/                 # RAG retrieval logic
├── ingestion/                 # Ingestion job management
├── vector_database/           # Weaviate integration and schemas
├── tracing/                   # Observability (LangFuse integration)
└── web/                       # FastAPI routers and status callbacks
```

### Key Entry Points

| File        | Purpose                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------------ |
| `main.py`   | Creates the FastAPI app, registers routers, initializes Sentry, LangFuse, and the LLM manager                |
| `config.py` | Loads `application.yml` via the `APPLICATION_YML_PATH` environment variable into a Pydantic `Settings` model |

### `common/` — Shared Utilities

```
common/
├── logging_config.py          # Structured logging with request correlation IDs
├── pyris_message.py           # PyrisMessage and IrisMessageRole (shared message format)
├── message_converters.py      # Convert between Iris and LangChain message formats
├── pipeline_enum.py           # PipelineEnum for token tracking
├── token_usage_dto.py         # TokenUsageDTO for tracking LLM costs
├── memiris_setup.py           # Memiris (memory system) integration utilities
├── singleton.py               # Singleton metaclass
├── mastery_utils.py           # Competency mastery calculations
└── custom_exceptions.py       # Custom exception types
```

### `domain/` — Data Models

Contains all Pydantic DTOs and variant configurations. See [Domain Models](./domain-models.md) for details.

```
domain/
├── pipeline_execution_dto.py              # Base DTO for all pipeline executions
├── pipeline_execution_settings_dto.py     # Settings (Artemis URL, auth token, variant)
├── feature_dto.py                         # Feature/variant description for Artemis
├── chat/                                  # Chat-specific DTOs
│   ├── chat_pipeline_execution_dto.py     # Base chat DTO (history, user, session)
│   ├── lecture_chat/                      # Lecture chat DTOs
│   └── text_exercise_chat/               # Text exercise chat DTOs
├── data/                                  # Shared data models
│   ├── course_dto.py, exercise DTOs, ...
│   └── metrics/                           # Student performance metrics
├── variant/                               # Variant configurations
│   ├── abstract_variant.py                # AbstractVariant, AbstractAgentVariant
│   └── exercise_chat_variant.py, ...      # Pipeline-specific variants
├── ingestion/                             # Ingestion pipeline DTOs
├── retrieval/                             # Retrieval result DTOs
├── status/                                # Stage/status DTOs
├── event/                                 # Event DTOs
└── communication/                         # Communication pipeline DTOs
```

### `pipeline/` — Pipeline System

The core of Iris. See [Pipeline System](./pipeline-system.md) for architecture details.

```
pipeline/
├── pipeline.py                            # Pipeline base class
├── sub_pipeline.py                        # SubPipeline base class
├── abstract_agent_pipeline.py             # AbstractAgentPipeline (agent loop)
├── chat/                                  # Chat pipelines
│   ├── exercise_chat_agent_pipeline.py    # Programming exercise chat
│   ├── course_chat_pipeline.py            # General course chat
│   ├── lecture_chat_pipeline.py           # Lecture-specific chat
│   ├── text_exercise_chat_pipeline.py     # Text exercise chat
│   ├── code_feedback_pipeline.py          # Internal code feedback analysis
│   └── interaction_suggestion_pipeline.py # Suggested follow-up questions
├── competency_extraction_pipeline.py      # Extract competencies from course content
├── inconsistency_check_pipeline.py        # Check FAQ consistency
├── lecture_ingestion_pipeline.py          # Ingest lecture PDFs into Weaviate
├── lecture_ingestion_update_pipeline.py   # Update existing ingested lectures
├── transcription_ingestion_pipeline.py    # Ingest lecture transcriptions
├── faq_ingestion_pipeline.py              # Ingest FAQs into Weaviate
├── rewriting_pipeline.py                  # Rewrite content for clarity
├── tutor_suggestion_pipeline.py           # Generate tutor suggestions for posts
├── autonomous_tutor_pipeline.py           # Autonomous tutor agent
├── session_title_generation_pipeline.py   # Generate chat session titles
├── shared/                                # Shared pipeline utilities
│   ├── citation_pipeline.py               # Citation generation sub-pipeline
│   └── utils.py                           # Tool generation, date formatting
└── prompts/                               # Prompt templates
    ├── templates/                         # Jinja2 templates (.j2 files)
    └── *.py, *.txt                        # Python prompt builders and text prompts
```

### `tools/` — LLM-Callable Tools

Functions that agents can call during execution. See [Tools](./tools.md) for the complete catalog.

```
tools/
├── lecture_content_retrieval.py            # RAG retrieval from lecture content
├── faq_content_retrieval.py               # RAG retrieval from FAQs
├── repository_files.py                    # List student repository files
├── file_lookup.py                         # Read specific file contents
├── submission_details.py                  # Get submission metadata
├── feedbacks.py                           # Get exercise feedback
├── build_logs_analysis.py                 # Analyze build logs
├── exercise_problem_statement.py          # Get exercise problem statement
├── exercise_list.py                       # List course exercises
├── exercise_example_solution.py           # Get exercise example solutions
├── additional_exercise_details.py         # Get additional exercise details
├── student_exercise_metrics.py            # Get student performance metrics
├── competency_list.py                     # List course competencies
├── course_details.py                      # Get course details
├── course_simple_details.py               # Get simplified course details
└── last_artifact.py                       # Get last CI/CD artifact
```

### `llm/` — LLM Client Layer

Abstractions over different LLM providers.

```
llm/
├── llm_manager.py                         # Singleton that loads models from YAML config
├── completion_arguments.py                # CompletionArguments (temperature, etc.)
├── request_handler/                       # Request routing
│   ├── model_version_request_handler.py   # Select model by version string
│   ├── rerank_request_handler.py          # Cohere reranking
│   └── request_handler_interface.py       # RequestHandler base class
├── external/                              # Provider-specific implementations
│   ├── model.py                           # Base LanguageModel, ChatModel, EmbeddingModel
│   ├── openai_chat.py                     # OpenAI chat completions
│   ├── openai_embeddings.py               # OpenAI embeddings
│   ├── openai_completion.py               # OpenAI text completions
│   ├── openai_dalle.py                    # DALL-E image generation
│   ├── ollama.py                          # Ollama (local models)
│   └── cohere_client.py                   # Cohere reranker client
└── langchain/                             # LangChain adapters
    └── iris_langchain_chat_model.py       # IrisLangchainChatModel wrapper
```

### `retrieval/` — RAG Retrieval

```
retrieval/
├── basic_retrieval.py                     # Basic vector similarity retrieval
├── faq_retrieval.py                       # FAQ retrieval pipeline
├── faq_retrieval_utils.py                 # FAQ retrieval utilities
└── lecture/                               # Lecture retrieval sub-system
    ├── lecture_retrieval.py               # Main lecture retrieval orchestrator
    ├── lecture_page_chunk_retrieval.py     # Retrieve lecture page chunks
    ├── lecture_transcription_retrieval.py  # Retrieve lecture transcriptions
    └── lecture_unit_segment_retrieval.py   # Retrieve lecture segments
```

### `vector_database/` — Weaviate Integration

```
vector_database/
├── database.py                            # VectorDatabase class (singleton client)
├── lecture_unit_page_chunk_schema.py       # Schema: Lectures collection
├── lecture_transcription_schema.py         # Schema: LectureTranscriptions collection
├── lecture_unit_segment_schema.py          # Schema: LectureUnitSegments collection
├── lecture_unit_schema.py                  # Schema: LectureUnits collection
└── faq_schema.py                          # Schema: FAQs collection
```

### `web/` — HTTP Layer

```
web/
├── routers/
│   ├── pipelines.py                       # Pipeline execution endpoints
│   ├── webhooks.py                        # Artemis webhook receivers
│   ├── ingestion_status.py                # Ingestion status endpoints
│   ├── memiris.py                         # Memory management endpoints
│   └── health/                            # Health check endpoint
├── status/
│   ├── status_update.py                   # Status callback implementations
│   └── ingestion_status_callback.py       # Ingestion-specific callbacks
└── utils.py                               # Variant validation utilities
```

### `tracing/` — Observability

```
tracing/
├── __init__.py                            # Exports: observe, TracingContext, etc.
└── langfuse_tracer.py                     # LangFuse integration (decorator, callbacks)
```

## Tests

```
tests/
├── test_dummy.py                              # Basic smoke test
└── test_session_title_generation_pipeline.py  # Session title generation tests
```

:::note
Test coverage is currently minimal. See [Testing](./testing.md) for how to run existing tests and add new ones.
:::
