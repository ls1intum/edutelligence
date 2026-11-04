---
title: Pipeline System
---

# Pipeline System

Iris models request handling as callable pipelines. This page is the source of truth for Iris-owned execution, callbacks, and RAG integration.

For configuration rather than control flow, use [LLM configuration](../admin/llm-configuration.md), the [variant system](./variant-system.md), and [developer configuration](./configuration.md).

## Hierarchy

| Type                    | Base                                  | Purpose                                                                                                                                                                                               |
| ----------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Pipeline`              | `pipeline/pipeline.py`                | Variant-aware, externally selectable callable pipeline. It records token usage, requires `__call__`, and derives `get_variants()` from class declarations unless a subclass supplies custom behavior. |
| `AbstractAgentPipeline` | `pipeline/abstract_agent_pipeline.py` | A `Pipeline` for tool-calling agents. It prepares state, selects the variant's local or cloud model role, builds tools and prompts, executes the agent, and finishes the callback.                    |
| `SubPipeline`           | `pipeline/sub_pipeline.py`            | Internal callable helper with no API variant contract. A parent pipeline owns its invocation and response.                                                                                            |

`AbstractAgentPipeline` supplies the agent loop and extension points for tools, prompts, pre/post hooks, token tracking, and streaming. Agent implementations decide which retrieval tools are enabled.

### Agent execution state and extension points

`Pipeline` subclasses are callable and identify their model roles and variants through `PIPELINE_ID`, `ROLES`, `VARIANT_DEFS`, and optional `DEPENDENCIES`. The base class derives variant requirements from those declarations, fails fast when a subclass omits `__call__`, and provides token-usage aggregation for nested stages.

`AbstractAgentPipeline` carries one `AgentPipelineExecutionState` through the run. The state keeps the request DTO and selected variant together with the callback, filtered message history, resolved model, prompt, tools, partial-result sender, retrieval results, token usage, tracing context, and a pending context switch. This lets hooks enrich one execution without introducing another top-level request contract.

| Extension category                       | Methods                                                                                                                         | Responsibility                                                                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Required                                 | `get_tools()`, `build_system_message()`                                                                                         | Define the agent's callable tools and system prompt.                                                                                            |
| Optional run customization               | `prepare_state()`, `pre_agent_hook()`, `post_agent_hook()`, `build_turn_context_message()`                                      | Resolve state that both the prompt and the tools depend on, add per-turn context after the history, or add behavior before and after execution. |
| Optional context/execution customization | `create_tracing_context()`, `get_max_agent_steps()`, `get_history_limit()`, `should_stream_agent_response()`, `execute_agent()` | Customize metadata, the step limit, retained history, streaming, or the execution strategy.                                                     |

Private helper methods implement the shared loop and should remain centralized in `AbstractAgentPipeline` rather than being copied into individual agents.

### The agent loop

Iris runs its own agent loop (`llm/agent/loop.py`) instead of LangChain's `AgentExecutor`. The loop and its tool adapter (`llm/agent/tools.py`) are about 400 lines together and do exactly what the chat needs:

1. Call the model with the prompt messages and the tool schemas.
2. If the answer has no tool calls, it is the final answer.
3. Otherwise send any text the model wrote next to its tool calls to the student once (as an intermediate message), run the tools, append their results, and go back to step 1.
4. After `get_max_agent_steps()` model calls with tools (15 by default), ask once more without tools for a final answer.

Design decisions and their reasons:

| Decision                                                                                                                                          | Reason                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| A tool error becomes text the model reads, like any tool result                                                                                   | One failing tool must not abort the whole chat. The model can retry or answer without it.                                                          |
| The model's provider items (for example OpenAI reasoning items with `encrypted_content`) are kept on the assistant message and sent back verbatim | Reasoning models keep their chain of thought between tool calls. Without it they plan again after every tool call, which costs tokens and quality. |
| Tool schemas are strict (`strict: true`, all fields required, no extra fields) where the model supports it                                        | The provider then guarantees valid arguments. `OpenAIChatModel.strict_tools` controls it; it defaults to on for the Responses API.                 |
| The forced final answer uses `tool_choice: "none"`, or no tools for models that ignore `tool_choice` (Ollama)                                     | The model cannot call a tool again at the step limit.                                                                                              |
| Usage is recorded after each model call, not only at the end                                                                                      | A run that fails in step 4 still reports the cost of steps 1 to 3.                                                                                 |

`IrisChatModel` (`llm/iris_chat_model.py`) is the small adapter between the loop and `LlmRequestHandler`. It also offers `structured(schema)` for side pipelines that need JSON instead of prose (see [Structured outputs](#structured-outputs)).

### Structured outputs

Side pipelines that need data pass a Pydantic model as `CompletionArguments.response_schema`. OpenAI and Azure models enforce the schema while decoding (`json_schema` with `strict: true`), Ollama gets it as `format`, and models that do not support schemas fall back to JSON mode (`supports_structured_output: false`). The answer is validated with the same Pydantic model (`llm/structured_output.py`). Session titles (`TitleDecision`), interaction suggestions (`Questions`) and citation labels (`CitationLabels`) use this instead of parsing free text such as `KEEP` or `UPDATE: <title>`.

### Retries

`llm/retry.py` decides retries for every OpenAI-compatible call. It retries rate limits, server errors and connection errors up to five attempts with exponential backoff and jitter, honours the provider's `retry-after-ms` and `retry-after` headers (up to 30 seconds), retries a timeout only once, and never retries other client errors such as 400. A caller can pass `CompletionArguments.cancel_event` to stop a retry wait at once; no pipeline sets it yet, because chat cancellation is still open.

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
| `POST /api/v1/webhooks/lectures/ingest`            | `LectureIngestionUpdatePipeline`                                                                                      | Raw `Thread` registered in `IngestionJobHandler` | `IngestionStatusCallback`. A new job supersedes a running one for the same base URL, course, lecture, and lecture unit; see [ingestion jobs](./ingestion-jobs.md).       |
| `POST /api/v1/webhooks/lectures/delete`            | `LectureUnitDeletionPipeline`                                                                                         | Raw `Thread`                                     | `LecturesDeletionStatusCallback`.                                                                                                                                        |
| `POST /api/v1/webhooks/faqs/ingest`                | `FaqIngestionPipeline`                                                                                                | Raw `Thread`                                     | `FaqIngestionStatus`.                                                                                                                                                    |
| `POST /api/v1/webhooks/faqs/delete`                | `FaqIngestionPipeline.delete_faq()`                                                                                   | Raw `Thread`                                     | `FaqIngestionStatus`.                                                                                                                                                    |

The FAQ ingestion/deletion and lecture-deletion routes deliberately do **not** use `IngestionJobHandler`; they start their own threads. The handler creates no processes and kills no threads: it starts every job immediately and signals a superseded one through a cancellation event that the pipeline observes at its own checkpoints.

### Chat modes

`ChatPipeline` is the shared top-level chat entry. Its `chat_mode` selects the appropriate course, exercise, lecture, text-exercise, or programming-exercise behavior; the selected mode determines prompts and tools rather than creating a second HTTP route. Code feedback is an internal helper used by applicable chat behavior, not another top-level callback pipeline.

`IrisChatMode` distinguishes `COURSE_CHAT`, `LECTURE_CHAT`, `PROGRAMMING_EXERCISE_CHAT`, and `TEXT_EXERCISE_CHAT`. The mode describes the **active context** of the chat, and three mechanisms consume it: `chat_system_prompt.j2` renders mode-specific blocks from a shared base (see [Prompts](./prompts.md)), `chat_tool_providers.py` decides per tool whether the current mode and the data Artemis sent make that tool useful (see [Tools](./tools.md)), and the quiz tool (`generate_mcq_questions`) is offered only in `COURSE` and `LECTURE` mode. One `ChatPipeline` serves all modes on purpose: a pipeline per mode would duplicate the agent setup, the retrieval wiring, and the citation handling, and it would make context switching impossible, since a running pipeline cannot hand a chat to a different one. `IrisChatMode` mirrors the Artemis enum, so both sides must agree on the string values.

### Context switching

Because the mode lives on the request rather than in the pipeline choice, a chat can change its active context between messages while keeping its history. A chat context changes in one of two ways:

- **The student switches it.** Artemis validates the target, persists a `CTXSWAP` marker message, and sends subsequent requests with the new `chat_mode` and the matching entity fields. Iris only has to interpret the marker it finds in the history.
- **The agent switches it.** The agent calls the `switch_chat_context` tool, which validates the target against the course data on the DTO and records it in `state.pending_context_switch`. Tools never mutate the session themselves. `post_agent_hook()` attaches the recorded switch to the final result as `suggestedContext`, and Artemis validates it again, applies it, and writes the `CTXSWAP` marker. The session context changes from the next message onwards, but lecture retrieval already follows the pending switch inside the same run, so the agent can answer about the new lecture immediately.

Both paths converge on the same marker, so the history stays uniform regardless of who initiated the switch. `AbstractAgentPipeline` treats markers in two places: `normalize_history_message()` renders them as a `[context_switch]` system message so the agent knows the topic changed, and `_collect_recent_messages()` drops everything up to and including the most recent marker so session-title generation reflects the current context instead of the previous one.

## Nested and internal pipelines

The following helpers run under a parent pipeline and return their result to that parent:

- Retrieval helpers: lecture retrieval, FAQ retrieval, and global-search retrieval.
- Response helpers: citations, summaries, session-title generation, interaction suggestions, and MCQ generation.
- Content helpers: lecture-unit and lecture-unit-segment summaries, transcription processing, and code feedback.
- Feature helpers: global-search intent classification and activity/confidence support.

See the [RAG pipeline](./rag-pipeline.md) for the lecture/FAQ ingestion, retrieval, reranking, and citation sequence.

## Extending chat behavior

Most chat work does not need a new pipeline. A new capability for student chats belongs in one of these places:

| Goal                                                     | Where it belongs                                                                                                                          |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Give the agent access to new data                        | A `create_tool_*` factory in `tools/` plus a `provide_*` function in `chat_tool_providers.py`                                             |
| Change what the agent is told, or how it behaves         | A block in `pipeline/prompts/templates/chat_system_prompt.j2`                                                                             |
| Add a new kind of context a chat can be attached to      | A member on `IrisChatMode`, the matching entity field on `ChatPipelineExecutionDTO`, a prompt block, and the corresponding Artemis change |
| Post-process the answer (citations, titles, suggestions) | A `SubPipeline` invoked from `ChatPipeline.post_agent_hook()`                                                                             |
| Act on what the student currently has open               | The `context` array on the request — see [viewing context](./viewing-context.md)                                                          |
| Drive the student's client mid-run                       | A typed `CommandDTO` sent from a tool through `callback.execute_command()` — see [client commands](./client-commands.md)                  |

## Creating a New Pipeline

When introducing a new externally triggered pipeline:

1. Define a typed request DTO under `domain/`, reusing `PipelineExecutionDTO` or the applicable chat DTO contract.
2. Implement `Pipeline` or `AbstractAgentPipeline` and declare its `PIPELINE_ID`, model `ROLES`, `VARIANT_DEFS`, and nested `DEPENDENCIES`. Orchestrators with no direct model role can derive requirements from dependencies.
3. Implement the required callable or agent extension points and place reusable internal stages in `SubPipeline` classes.
4. Add prompts under the pipeline prompt packages/templates rather than embedding deployment-specific model assumptions in the route.
5. Register an authenticated route and worker in the applicable router. Validate the requested variant before starting asynchronous work and use a typed status callback for the result path.
6. Add tests for variant requirements, worker/callback behavior, and the pipeline itself, then update the Artemis integration contract if Artemis must invoke the new route.

Do not create a second public route for behavior that is only a chat mode or a nested helper; keep those choices inside their owning top-level pipeline.
