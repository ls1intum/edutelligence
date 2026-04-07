---
title: Pipeline System
---

# Pipeline System

The pipeline system is the architectural backbone of Iris. Every piece of work — answering a student question, ingesting a lecture, extracting competencies — is modeled as a **pipeline**.

## Base Classes

Iris has three pipeline base classes, each serving a different purpose:

### `Pipeline` — Top-level Pipelines

**Location:** `src/iris/pipeline/pipeline.py`

All externally-triggered pipelines inherit from `Pipeline`. It is a generic abstract class parameterized by a variant type:

```python
class Pipeline(Generic[VARIANT], metaclass=ABCMeta):
    implementation_id: str
    tokens: List[TokenUsageDTO]

    @abstractmethod
    def __call__(self, **kwargs):
        """Extracts the required parameters from the kwargs and runs the pipeline."""
        ...

    @classmethod
    @abstractmethod
    def get_variants(cls) -> List[AbstractVariant]:
        """Returns all available variants for this pipeline."""
        ...
```

Key characteristics:

- **`__call__`** is the entry point — every pipeline is callable.
- **`get_variants()`** returns the list of variant configurations available for this pipeline (exposed to Artemis for selection).
- **`__init_subclass__`** enforces that every subclass implements `__call__` at class definition time, failing fast if forgotten.
- **`_append_tokens()`** tracks LLM token usage per pipeline stage.

### `AbstractAgentPipeline` — Agent-based Pipelines

**Location:** `src/iris/pipeline/abstract_agent_pipeline.py`

Most chat pipelines inherit from this class, which provides the full agent execution loop:

```python
class AbstractAgentPipeline(ABC, Pipeline, Generic[DTO, VARIANT]):
    ...
```

It is parameterized by both a **DTO** type (the request data) and a **VARIANT** type (the configuration). The `__call__` method orchestrates the entire agent lifecycle:

1. **Initialize state** — Create `AgentPipelineExecutionState` with the DTO, variant, callback, tools, and LLM.
2. **Prepare message history** — Filter empty messages, extract recent chat history.
3. **Select LLM** — Choose cloud or local model from the variant configuration.
4. **Build prompt** — Call `build_system_message()` and `assemble_prompt_with_history()`.
5. **Load tools** — Call `get_tools()` to get the callable functions for this pipeline.
6. **Start memory creation** — Optionally run Memiris memory creation in a background thread.
7. **Execute agent** — Run the LangChain tool-calling agent loop via `execute_agent()`.
8. **Post-processing** — Run `post_agent_hook()`, wait for memory creation, signal completion.

#### Methods to Override

The class is designed with clear extension points:

| Category              | Method                                 | Purpose                                           |
| --------------------- | -------------------------------------- | ------------------------------------------------- |
| **MUST override**     | `get_tools()`                          | Return list of callable tool functions            |
| **MUST override**     | `build_system_message()`               | Return the system prompt string                   |
| **MUST override**     | `is_memiris_memory_creation_enabled()` | Whether to create memories                        |
| **MUST override**     | `get_memiris_tenant()`                 | Memiris tenant identifier                         |
| **MUST override**     | `get_memiris_reference()`              | Memiris reference for learnings                   |
| **CAN override**      | `pre_agent_hook()`                     | Run logic before agent execution                  |
| **CAN override**      | `post_agent_hook()`                    | Run logic after agent execution                   |
| **CAN override**      | `on_agent_step()`                      | Called per agent iteration step                   |
| **CAN override**      | `get_agent_params()`                   | Extra parameters for the agent                    |
| **CAN override**      | `get_history_limit()`                  | How many recent messages to include (default: 15) |
| **CAN override**      | `execute_agent()`                      | Replace the default agent execution logic         |
| **MUST NOT override** | `_create_agent_executor()`             | Internal: builds the LangChain agent              |
| **MUST NOT override** | `_run_agent_iterations()`              | Internal: runs the agent loop                     |

#### Execution State

The `AgentPipelineExecutionState` dataclass holds everything needed during pipeline execution:

```python
class AgentPipelineExecutionState(Generic[DTO, VARIANT]):
    db: VectorDatabase
    dto: DTO
    variant: VARIANT
    callback: StatusCallback
    message_history: list[PyrisMessage]
    tools: list[Callable]
    result: str
    llm: Any | None
    prompt: ChatPromptTemplate | None
    tokens: List[TokenUsageDTO]
    local: bool
    tracing_context: Optional[TracingContext]
    # ... plus Memiris fields
```

### `SubPipeline` — Internal Pipelines

**Location:** `src/iris/pipeline/sub_pipeline.py`

Sub-pipelines are used internally by other pipelines. They do **not** expose variants and are not directly callable from the API:

```python
class SubPipeline(metaclass=ABCMeta):
    implementation_id: str
    tokens: List[TokenUsageDTO]

    @abstractmethod
    def __call__(self, **kwargs):
        ...
```

Examples of sub-pipelines:

- `LectureRetrieval` — RAG retrieval from lecture content
- `CitationPipeline` — Generate citations from retrieved content
- `SessionTitleGenerationPipeline` — Generate chat session titles
- `CodeFeedbackPipeline` — Internal code analysis feedback
- `InteractionSuggestionPipeline` — Generate follow-up question suggestions

## Available Pipelines

### Chat Pipelines (Agent-based)

| Pipeline                    | DTO                                    | Description                   |
| --------------------------- | -------------------------------------- | ----------------------------- |
| `ExerciseChatAgentPipeline` | `ExerciseChatPipelineExecutionDTO`     | Programming exercise tutoring |
| `CourseChatPipeline`        | `CourseChatPipelineExecutionDTO`       | General course Q&A            |
| `LectureChatPipeline`       | `LectureChatPipelineExecutionDTO`      | Lecture content Q&A           |
| `TextExerciseChatPipeline`  | `TextExerciseChatPipelineExecutionDTO` | Text exercise tutoring        |
| `AutonomousTutorPipeline`   | `AutonomousTutorPipelineExecutionDTO`  | Autonomous tutor agent        |

### Ingestion Pipelines

| Pipeline                           | Description                                       |
| ---------------------------------- | ------------------------------------------------- |
| `LectureUnitPageIngestionPipeline` | Parse lecture PDFs, chunk text, store in Weaviate |
| `LectureIngestionUpdatePipeline`   | Update existing lecture ingestions                |
| `TranscriptionIngestionPipeline`   | Ingest lecture transcriptions                     |
| `FaqIngestionPipeline`             | Ingest FAQ entries                                |

### Other Pipelines

| Pipeline                       | Description                                   |
| ------------------------------ | --------------------------------------------- |
| `CompetencyExtractionPipeline` | Extract competencies from course descriptions |
| `InconsistencyCheckPipeline`   | Check FAQ content for inconsistencies         |
| `RewritingPipeline`            | Rewrite content for clarity                   |
| `TutorSuggestionPipeline`      | Generate tutor suggestions for forum posts    |

## Pipeline Dispatch

Pipelines are dispatched from two FastAPI routers:

- **`web/routers/pipelines.py`** — Chat, competency extraction, rewriting, and other request-response pipelines.
- **`web/routers/webhooks.py`** — Ingestion and deletion pipelines triggered by Artemis webhooks.

Chat pipeline endpoints follow this pattern:

1. Validate the request DTO.
2. Resolve the requested variant using `validate_pipeline_variant()`.
3. Spawn a **background thread** to run the pipeline (endpoints return `202 Accepted` immediately).
4. The pipeline communicates progress back to Artemis via **status callbacks**.

Ingestion pipelines use a different pattern — they spawn a **`multiprocessing.Process`** instead of a thread, managed by the `IngestionJobHandler`.

Example endpoint registration for a chat pipeline:

```python
@router.post(
    "/programming-exercise-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_exercise_chat_pipeline(
    event: str | None = Query(None),
    dto: ExerciseChatPipelineExecutionDTO = Body(...),
):
    variant = validate_pipeline_variant(dto.settings, ExerciseChatAgentPipeline)
    thread = Thread(target=run_exercise_chat_pipeline_worker, args=(dto, variant, event, request_id))
    thread.start()
```

## Creating a New Pipeline

To add a new pipeline to Iris:

1. **Define the DTO** — Create a Pydantic model in `domain/` that extends `PipelineExecutionDTO` (or `ChatPipelineExecutionDTO` for chat pipelines).

2. **Create a variant class** — Extend `AbstractAgentVariant` (for agent pipelines) or `AbstractVariant` in `domain/variant/`.

3. **Implement the pipeline** — Create a class extending `AbstractAgentPipeline[YourDTO, YourVariant]` and implement the required methods:
   - `get_tools()` — return the tools the agent can use
   - `build_system_message()` — return the system prompt
   - `get_variants()` — return available variant configurations
   - Memiris methods (`is_memiris_memory_creation_enabled`, `get_memiris_tenant`, `get_memiris_reference`)

4. **Add prompts** — Create a Jinja2 template in `pipeline/prompts/templates/` or a Python prompt builder in `pipeline/prompts/`.

5. **Register the endpoint** — Add a route in `web/routers/pipelines.py` with the worker function and endpoint decorator.

6. **Register in Artemis** — The Artemis side needs a corresponding feature configuration to call the new pipeline.
