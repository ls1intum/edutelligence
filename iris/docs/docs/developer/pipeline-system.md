---
title: Pipeline System
---

# Pipeline System

Iris models request handling as callable pipelines. This page is the source of truth for Iris-owned execution, callbacks, RAG integration, and the Iris integration of the [Memiris library](https://github.com/ls1intum/edutelligence/tree/main/memiris). The library's reusable creation and sleep pipelines are documented in its own README; Iris owns how they are configured and run here.

For configuration rather than control flow, use [LLM configuration](../admin/llm-configuration.md), the [variant system](./variant-system.md), and [developer configuration](./configuration.md).

## Hierarchy

| Type                    | Base                                  | Purpose                                                                                                                                                                                               |
| ----------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Pipeline`              | `pipeline/pipeline.py`                | Variant-aware, externally selectable callable pipeline. It records token usage, requires `__call__`, and derives `get_variants()` from class declarations unless a subclass supplies custom behavior. |
| `AbstractAgentPipeline` | `pipeline/abstract_agent_pipeline.py` | A `Pipeline` for tool-calling agents. It prepares state, selects the variant's local or cloud model role, builds tools and prompts, executes the agent, and finishes the callback.                    |
| `SubPipeline`           | `pipeline/sub_pipeline.py`            | Internal callable helper with no API variant contract. A parent pipeline owns its invocation and response.                                                                                            |

`AbstractAgentPipeline` supplies the agent loop and extension points for tools, prompts, pre/post hooks, token tracking, and streaming. Agent implementations decide whether memory creation and individual retrieval tools are enabled.

### Agent execution state and extension points

`Pipeline` subclasses are callable and identify their model roles and variants through `PIPELINE_ID`, `ROLES`, `VARIANT_DEFS`, and optional `DEPENDENCIES`. The base class derives variant requirements from those declarations, fails fast when a subclass omits `__call__`, and provides token-usage aggregation for nested stages.

`AbstractAgentPipeline` carries one `AgentPipelineExecutionState` through the run. The state keeps the request DTO and selected variant together with the callback, filtered message history, resolved model, prompt, tools, partial-result sender, retrieval results, token usage, tracing context, and optional Memiris state. This lets hooks enrich one execution without introducing another top-level request contract.

| Extension category                       | Methods                                                                                                                      | Responsibility                                                                                                                                                             |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Required                                 | `get_tools()`, `build_system_message()`                                                                                      | Define the agent's callable tools and system prompt.                                                                                                                       |
| Required for the shared memory contract  | `is_memiris_memory_creation_enabled()`, `get_memiris_tenant()`, `get_memiris_reference()`                                    | Decide whether the run participates in memory creation and provide its isolation/reference keys. These methods still return safe values when Memiris is disabled globally. |
| Optional run customization               | `pre_agent_hook()`, `post_agent_hook()`, `on_agent_step()`                                                                   | Add behavior before execution, after execution, or after an individual agent step.                                                                                         |
| Optional context/execution customization | `create_tracing_context()`, `get_agent_params()`, `get_history_limit()`, `should_stream_agent_response()`, `execute_agent()` | Customize metadata, executor arguments, retained history, streaming, or the execution strategy.                                                                            |

Private helper methods implement the shared loop and should remain centralized in `AbstractAgentPipeline` rather than being copied into individual agents.

## Externally triggered pipelines

All listed routes are authenticated and return `202 Accepted` for asynchronous work. The route normally starts a worker and the worker sends status to the Artemis base URL carried in the request.

| Route or trigger                                   | Top-level pipeline                                                                                                    | Execution                                        | Result path                                                                                                                                                              |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /api/v1/pipelines/chat/run`                  | `ChatPipeline`                                                                                                        | Raw `Thread`                                     | `ChatRunCallback`; optional partial-result delivery is handled by the agent pipeline.                                                                                    |
| `POST /api/v1/pipelines/autonomous-tutor/run`      | `AutonomousTutorPipeline`                                                                                             | Raw `Thread`                                     | `AutonomousTutorCallback`.                                                                                                                                               |
| `POST /api/v1/pipelines/tutor-suggestion/run`      | `TutorSuggestionPipeline`                                                                                             | Raw `Thread`                                     | `TutorSuggestionCallback`.                                                                                                                                               |
| `POST /api/v1/pipelines/competency-extraction/run` | `CompetencyExtractionPipeline`                                                                                        | Raw `Thread`                                     | `CompetencyExtractionCallback`.                                                                                                                                          |
| `POST /api/v1/pipelines/rewriting/run`             | `RewritingPipeline`                                                                                                   | Raw `Thread`                                     | `RewritingCallback`; current Artemis has neither a caller nor a matching callback endpoint, so this Iris route is not an active end-to-end Artemis integration.          |
| `POST /api/v1/pipelines/inconsistency-check/run`   | `InconsistencyCheckPipeline`                                                                                          | Raw `Thread`                                     | `InconsistencyCheckCallback`; current Artemis has neither a caller nor a matching callback endpoint, so this Iris route is not an active end-to-end Artemis integration. |
| `POST /api/v1/pipelines/global-search/run`         | Route worker orchestrator; conditionally invokes `GlobalSearchPipeline` (a `SubPipeline`) for answer-producing intent | Shared `TracedThreadPoolExecutor`                | `GlobalSearchCallback` with the answer, sources, and token usage. The sources-only (`SKIP_AI`) branch retrieves directly and sends no LLM answer.                        |
| `POST /api/v1/webhooks/lectures/ingest`            | `LectureIngestionUpdatePipeline`                                                                                      | Raw `Thread` registered in `IngestionJobHandler` | `IngestionStatusCallback`. Duplicate suppression is scoped only to the same course, lecture, and lecture unit.                                                           |
| `POST /api/v1/webhooks/lectures/delete`            | `LectureUnitDeletionPipeline`                                                                                         | Raw `Thread`                                     | `LecturesDeletionStatusCallback`.                                                                                                                                        |
| `POST /api/v1/webhooks/faqs/ingest`                | `FaqIngestionPipeline`                                                                                                | Raw `Thread`                                     | `FaqIngestionStatus`.                                                                                                                                                    |
| `POST /api/v1/webhooks/faqs/delete`                | `FaqIngestionPipeline.delete_faq()`                                                                                   | Raw `Thread`                                     | `FaqIngestionStatus`.                                                                                                                                                    |

The FAQ ingestion/deletion and lecture-deletion routes deliberately do **not** use `IngestionJobHandler`; they start their own threads. The handler no longer creates processes or terminates/restarts workers.

### Chat modes

`ChatPipeline` is the shared top-level chat entry. Its `chat_mode` selects the appropriate course, exercise, lecture, text-exercise, or programming-exercise behavior; the selected mode determines prompts and tools rather than creating a second HTTP route. Code feedback is an internal helper used by applicable chat behavior, not another top-level callback pipeline.

## Nested and internal pipelines

The following helpers run under a parent pipeline and return their result to that parent:

- Retrieval helpers: lecture retrieval, FAQ retrieval, and global-search retrieval.
- Response helpers: citations, summaries, session-title generation, interaction suggestions, and MCQ generation.
- Content helpers: lecture-unit and lecture-unit-segment summaries, transcription processing, and code feedback.
- Feature helpers: global-search intent classification and activity/confidence support.

See the [RAG pipeline](./rag-pipeline.md) for the lecture/FAQ ingestion, retrieval, reranking, and citation sequence.

## Creating a New Pipeline

When introducing a new externally triggered pipeline:

1. Define a typed request DTO under `domain/`, reusing `PipelineExecutionDTO` or the applicable chat DTO contract.
2. Implement `Pipeline` or `AbstractAgentPipeline` and declare its `PIPELINE_ID`, model `ROLES`, `VARIANT_DEFS`, and nested `DEPENDENCIES`. Orchestrators with no direct model role can derive requirements from dependencies.
3. Implement the required callable or agent extension points and place reusable internal stages in `SubPipeline` classes.
4. Add prompts under the pipeline prompt packages/templates rather than embedding deployment-specific model assumptions in the route.
5. Register an authenticated route and worker in the applicable router. Validate the requested variant before starting asynchronous work and use a typed status callback for the result path.
6. Add tests for variant requirements, worker/callback behavior, and the pipeline itself, then update the Artemis integration contract if Artemis must invoke the new route.

Do not create a second public route for behavior that is only a chat mode or a nested helper; keep those choices inside their owning top-level pipeline.

## Iris-owned Memiris integration

Memiris is optional and controlled by Iris configuration. `MemirisWrapper` in `common/memiris_setup.py` maps Iris model-role configuration to Memiris-compatible language and embedding models, creates local and cloud creation/sleep pipelines, and exposes services over Iris's vector-database client. It is not a replacement for the reusable library's builders, repositories, or schemas.

`AbstractAgentPipeline` creates a wrapper for the pipeline's tenant. A participating agent can:

1. start memory creation in a context-propagating background thread;
2. wait for that thread before its final callback, including created memories when present;
3. offer semantic memory search and similar-memory tools, which record accessed memories; and
4. isolate storage through the pipeline-provided tenant and reference.

The active Memiris routes are:

- `GET /api/v1/memiris/user/{user_id}` returns the tenant's memory list using the legacy v1 response shape.
- `GET /api/v2/memiris/user/{user_id}` returns aggregate memory data: memories, learnings, and the memory-connection graph.
- `DELETE /api/v1/memiris/user/{user_id}/delete-all` deletes all memories, learnings, and connections for the tenant.
- `GET /api/v1/memiris/user/{user_id}/{memory_id}` retrieves one memory with its relations, and `DELETE` on the same path deletes that memory.

### Periodic sleep orchestration

The reusable `MemorySleepPipeline.sleep(tenant)` is a Memiris library operation. Iris separately schedules `memory_sleep_task` through its application `BackgroundScheduler`. The task is gated by Iris's Memiris and sleep settings, limits work to Artemis-user tenants, retains only tenants with unslept memories, and invokes the wrapper's sleep operation for each remaining tenant. It has no per-request Artemis callback.

This distinction matters: Memiris owns the generic creation/sleep algorithm and repository contracts; Iris owns its model-role conversion, feature gates, tenant policy, tools, background creation, and periodic sleep scheduling.
