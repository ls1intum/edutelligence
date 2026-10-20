---
title: Global Search
---

# Global Search

Artemis global search calls Iris for two things: the slide and transcript hits of the **Slides & Videos** search, and the Iris answer above the results. This page is the source of truth for the Iris side of both: the routes, the request and status contract, the access rules, retrieval, and answer generation. It does not describe the Artemis search index of courses, exercises and other entities, which Artemis owns; see the [Artemis Weaviate setup](https://docs.artemis.cit.tum.de/developer/weaviate-setup). What the student sees is described in the [Artemis global search guide](https://docs.artemis.cit.tum.de/student/getting-started/global-search).

Model roles and providers belong in [LLM configuration](../admin/llm-configuration.md) and [developer configuration](./configuration.md). The lecture collections that global search reads are written by the ingestion described in the [RAG pipeline](./rag-pipeline.md) and [ingestion reliability](./ingestion-reliability.md).

## Architecture overview

```text
Content search: Artemis -> POST /api/v1/search/lectures -> LectureGlobalSearchRetrieval -> result list (synchronous)
Iris answer:    Artemis -> POST /api/v1/pipelines/global-search/run -> intent classifier
                  -> SKIP_AI:    LectureGlobalSearchRetrieval -> terminal status (sources only)
                  -> TRIGGER_AI: GlobalSearchPipeline -> stage and partial status -> terminal status (answer and sources)
                -> Artemis -> websocket /topic/iris/global-search-answer -> search palette
```

Both paths share one retriever, `LectureGlobalSearchRetrieval`, so a content hit and an answer source are found, scoped and filtered the same way. The answer path additionally receives entity candidates (exercises, exams, FAQs, channels, lectures, lecture units and courses) that Artemis has already authorized, and lets them compete with the lecture content in one reranked pool.

## Routes

| Route                                      | Artemis caller                                          | Execution                                                                                | Result path                                                                                                                                                        |
| ------------------------------------------ | ------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /api/v1/search/lectures`             | `PyrisConnectorService.searchLectures()`                | Synchronous, on the request thread                                                       | The response body: a list of `LectureSearchResultDTO`.                                                                                                             |
| `POST /api/v1/pipelines/global-search/run` | `PyrisConnectorService.executeGlobalSearchIrisAnswer()` | `run_global_search_pipeline_worker` on a shared `TracedThreadPoolExecutor` (100 workers) | `202 Accepted`; `GlobalSearchCallback` posts `GlobalSearchStatusUpdateDTO` to `{artemis_base_url}/api/iris/internal/pipelines/global-search/runs/{run_id}/status`. |

Both routes require the shared Artemis token (`TokenValidator`). The run id is the `authentication_token` of the execution settings; Artemis uses it to route the status updates back to the user who asked, and discards updates for a run it no longer tracks.

## Request contract

`GlobalSearchRequestDTO` (`domain/search/global_search_dto.py`) is the answer request. `LectureSearchRequestDTO` carries the same scope fields for the content search, with `limit` between 1 and 20 (default 10) and the Artemis base URL as a top-level `artemisBaseUrl`.

| Field                | Wire name          | Meaning                                                                                                                                                                                                               |
| -------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `query`              | `query`            | The text the student typed. Blank queries are rejected.                                                                                                                                                               |
| `limit`              | `limit`            | Maximum number of lecture sources, 1 to 10, default 5.                                                                                                                                                                |
| `settings`           | `settings`         | `PipelineExecutionSettingsDTO`: the run id as `authenticationToken`, `artemisBaseUrl`, `streamResponse`, and `selection`, the student's AI choice (`LOCAL_AI` or `CLOUD_AI`), which selects the local or cloud model. |
| `access_context`     | `accessContext`    | What the student may see; see [Access rules](#access-rules).                                                                                                                                                          |
| `entity_candidates`  | `entityCandidates` | Up to 25 `EntityCandidateDTO` rows that Artemis prefetched from its own index with the search palette's access filter.                                                                                                |
| `course_ids`         | `courseIds`        | The course filter of the palette, already narrowed by Artemis to courses with Iris enabled. Absent means unscoped.                                                                                                    |
| `exclude_course_ids` | `excludeCourseIds` | Courses to hide. Only sent for an unrestricted caller, which has no course list that Artemis could narrow itself.                                                                                                     |
| `searches_nothing`   | `searchesNothing`  | True when the student's exclusions removed every course. Artemis drops empty lists from the wire, so this flag is what tells "nothing" apart from "unscoped".                                                         |

All fields except `query` and `settings` are optional, and every field added later must stay optional, because an older Artemis does not send it.

## Access rules

Iris has no user or course model of its own. Artemis resolves the student's permissions into an `AccessContext` and Iris applies it as an opaque filter on every retriever call:

| Field                                                | Meaning                                                                                      |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `courseIds`                                          | Every course the user can access.                                                            |
| `editorCourseIds`, `taCourseIds`, `studentCourseIds` | The same courses, grouped by the user's role in them.                                        |
| `staffCourseIds`                                     | Editor and tutor courses together; staff see unreleased lecture units.                       |
| `now`                                                | The Artemis request time. Release dates are compared against it, not against the Iris clock. |
| `unrestricted`                                       | True for administrators: no course ceiling and no release gate.                              |

The retriever applies the context in three steps:

1. `resolve_effective_course_ids()` intersects the requested course filter with `courseIds`; an empty result skips the search before anything is embedded;
2. the course filter, and for an unrestricted caller the excluded courses, are part of the Weaviate query; and
3. `_VisibilityPolicy` filters the returned rows: a lecture unit is kept for a student only once its release date has passed at `now`, while staff of that course and administrators skip this gate. A slide whose `hidden_until` lies in the future is dropped for every role, staff included.

Every row must also belong to the requesting Artemis. The query filters with `artemis_instance_filter()`: on `base_url_exact` once a collection's older rows carry it, and until then on the word-tokenized `base_url`, which also matches longer URLs that contain the requested one. The policy therefore compares the stored `base_url` with the requested one again after the query. One Iris can serve several Artemis instances without one seeing the other's content; see [Several Artemis instances on one Iris](../admin/weaviate-setup.md#several-artemis-instances-on-one-iris).

The entity candidates need no second check. Artemis selected them with the same access filter as its search palette, including exam registrations and channel visibility, which Iris could not reconstruct.

## Intent classification

Not every search deserves an answer. `classify_intent()` (`pipeline/shared/global_search_intent_classifier.py`) decides per query between `TRIGGER_AI` and `SKIP_AI` before any retrieval runs. It is a SetFit classifier, a sentence-transformer body exported to INT8-quantized ONNX with a logistic-regression head, and runs on the CPU in about 2 ms.

| Outcome      | What happens                                                                                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TRIGGER_AI` | The worker sends a first status update with no answer, which shows the thinking state, and runs `GlobalSearchPipeline`.                                                 |
| `SKIP_AI`    | The worker retrieves lecture sources and sends one terminal update with `answer = null`. Because no thinking update preceded it, the palette shows no Iris card at all. |

The Docker image downloads the model file from the `NayerKotry/iris-intent-classifier` repository on Hugging Face at a pinned revision, verifies its SHA-256, and sets `INTENT_MODEL_DIR=/app/models/global_search_intent/onnx`. The tokenizer is fetched at runtime, also at a pinned revision. `main.py` loads the classifier in a background thread at startup, so the first request does not wait for it.

If the model directory is missing, the classifier is disabled for the lifetime of the process and logs one warning. If loading fails for another reason, it is retried on the next query. In both cases `classify()` returns `TRIGGER_AI`: a missing classifier costs an LLM call, but never drops a real question.

## Retrieval

`LectureGlobalSearchRetrieval.search()` (`retrieval/lecture/lecture_global_search_retrieval.py`) runs in two stages: recall lanes collect candidates cheaply, and a shared cross-encoder decides their order and whether they are good enough.

### Recall

The query is embedded once with the `embedding` model of `global_search_pipeline`. If that model entry sets `retrieval_instruction`, the instruction is put in front of the query, which instruction-tuned models such as Qwen3-Embedding expect for asymmetric retrieval; `QWEN3_RETRIEVAL_INSTRUCTION` is the reference wording for it. Stored documents are always embedded without an instruction, and a plain OpenAI or Azure entry must not set one, because the model would embed the instruction as part of the query. Two hybrid searches run in parallel with `alpha` 0.75, so the vector score outweighs the keyword score:

| Lane                    | Content                                                                    |
| ----------------------- | -------------------------------------------------------------------------- |
| `LectureUnitSegments`   | Slide-based segments: a slide's text together with what was said about it. |
| `LectureTranscriptions` | Transcript passages of a video that has no slide for them.                 |

Each lane returns up to 25 candidates. Before ranking, the retriever removes rows that fail the [access rules](#access-rules), placeholder text that ingestion wrote for empty slides or silent videos, and near-duplicate slides that several courses ingested from the same deck.

### Ranking

The candidates, and on the answer path the rendered entity candidates, go to one reranker call, so lecture passages and course information are compared on a single scale. The reranker is the `reranker` role of `global_search_pipeline`, falling back to that of `lecture_retrieval_pipeline`. Without a reranker, or when the call fails or exceeds its budget, the retriever keeps the fused Weaviate order and returns lecture content only, because entity candidates have no comparable score without the reranker.

After reranking, `global_search_rerank_floor` removes candidates that score like unrelated text. The floor is calibrated against Qwen3-Reranker-8B and only applied when the reranker's configuration entry declares `rerank_floor_calibrated`. It is deliberately not tuned to keep only strong matches: a cut inside the relevant band would delete real answers and fall within the reranker's run-to-run noise. Three further rules shape what survives:

- the best entity cards and the best content passage each keep a slot, even when the other kind fills the top ranks;
- when nothing clears the floor, up to three entity cards from just below it are admitted as pointers, so the answer can direct the student to material instead of saying nothing; and
- when the same entity exists in several semesters of a course, only the most recent instance that is already visible is kept. A query that names a semester or a year is exempt, because the student may be asking about an earlier run.

### Unit expansion

Ranking makes every passage of a lecture unit compete for a slot, although the answer is already known to live in that unit. On the answer path, the retriever therefore takes the best surviving units (`global_search_expand_max_units`, default 4) and fetches up to `global_search_expand_per_unit` further passages of each (default 3) by their unit key instead of ranking them. The expanded passages follow the ranked ones and keep their anchor's score.

The result list of the content search is neither expanded nor, by default, reranked (`global_search_rerank_results_list`), so it answers within about a second.

## Answer generation

`GlobalSearchPipeline` (`pipeline/global_search_pipeline.py`) is a `SubPipeline` with two model roles, `answer` and `embedding`, each with a local and a cloud variant chosen by the student's AI choice. It runs the following sequence:

1. send the `searching` stage, render the entity candidates into cards, and retrieve sources as described above, sending `ranking` before the reranker call;
2. drop sources without text and send `found` with the names of the courses the sources come from;
3. choose the prompt: `navigate_system_prompt` when every remaining source is an entity pointer, otherwise `answer_system_prompt`;
4. send `generating` and call the answer model on the numbered sources, streaming the draft when `streamResponse` is set;
5. parse the output, and if the grounded prompt produced no answer although entity sources exist, retry once with the navigation prompt on those sources; and
6. sanitize and renumber the citation markers and send the terminal update.

### Prompts

Both prompts are plain text in `pipeline/prompts/global_search_prompts.py`. The answer prompt restricts the model to the numbered sources, asks for a marker after every factual claim, limits the answer to 300 words, and forbids code that is not in the sources. The navigation prompt does not answer the question; it names the course and the lecture, unit or exercise that covers it in one or two sentences.

The model writes markdown directly rather than JSON, because a JSON envelope cannot be shown while it streams. A model that cannot answer writes exactly `!none!`, which is the only no-answer signal; the pipeline holds back the streamed draft until it can no longer turn out to be that sentinel. The instruction to answer in the language of the question stands at the end of the user message rather than only in the system prompt, because light models otherwise follow the language of the sources. When an answer may depend on the semester, the user message also states the request date.

The navigation retry does not run when the model deliberately wrote `!none!`. The grounded prompt also answers `!none!` for an unfinished question, and the more lenient navigation prompt would otherwise override that judgment.

### Citations

The answer cites sources with `[n]` markers that refer to the numbered context. Before anything reaches the student, `sanitize_citation_markers()` removes markers outside the numbered range, collapses repeated markers, and keeps chains such as `[1][3]` as multi-source citations. Only the sources that the answer actually cites are returned, so `renumber_citation_markers()` renumbers the markers in the order in which each source is first cited, regardless of whether it is a lecture source or an entity.

The response still carries lecture sources (`sources`) and entity sources (`entitySources`) in two arrays. `citationSourceTypes` lists, for marker 1 to N, whether it resolves into `lecture` or `entity`; the client walks it with one counter per array. Without it, a client cannot tell which array a marker belongs to whenever citations of both kinds interleave.

## Status updates

`GlobalSearchStatusUpdateDTO` (`domain/status/global_search_status_update_dto.py`) carries every update of a run:

| Update   | Fields set                                                                           | Sent when                                                       |
| -------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| Thinking | none                                                                                 | Right after a `TRIGGER_AI` classification.                      |
| Stage    | `stage` (`searching`, `ranking`, `found`, `generating`), `stageSources` with `found` | At the start of each phase of the pipeline.                     |
| Partial  | `partialResult`, `partialSeq`                                                        | While the answer streams; `PartialResultSender` batches deltas. |
| Terminal | `answer` (or `null`), `sources`, `entitySources`, `citationSourceTypes`, token usage | Once, at the end of a run.                                      |
| Failure  | the failed run state                                                                 | When the worker raises; the palette offers **Try again**.       |

Partial updates are numbered, so Artemis can discard one that arrives after a newer one. A partial update carries no sources, so its markers are only checked against an upper bound; the terminal update replaces the draft with the sanitized answer. When the navigation retry starts, the pipeline clears the streamed draft so the student does not keep reading an answer that was discarded.

`stage`, `stageSources`, `entitySources` and `citationSourceTypes` were added to the contract after its first version. An Artemis that does not know them ignores them and falls back to its generic thinking state and to lecture sources only.

## Configuration

The models are assigned in `application.yml` under `llm_configuration.global_search_pipeline`:

```yaml
global_search_pipeline:
  default:
    answer:
      local: qwen3.8-27b
      cloud: oai-gpt-5-mini-minimal
    embedding: qwen3-embedding
    reranker: qwen3-reranker
```

The embedding must be the model that ingestion used for the lecture collections. For an instruction-tuned model such as Qwen3-Embedding, set its `retrieval_instruction`; see [Retrieval Instruction](../admin/llm-configuration.md#retrieval-instruction). The `reranker` role is optional, but without it the answer draws on lecture content only; see [Ranking](#ranking) and the [vLLM reranker](../admin/llm-configuration.md#vllm-reranker-vllm_rerank) entry, whose `rerank_floor_calibrated` decides whether the floor applies. The TUM deployment serves the embedding and the reranker (Qwen3-Embedding-8B and Qwen3-Reranker-8B) through Logos. Answer latency depends mostly on the answer model: the pipeline caps it at 600 output tokens, and the example assigns a model with minimal [reasoning effort](../admin/llm-configuration.md#reasoning-effort).

| Setting                               | Default | Effect                                                             |
| ------------------------------------- | ------- | ------------------------------------------------------------------ |
| `global_search_rerank_floor`          | `0.10`  | Reranker score below which a candidate counts as unrelated.        |
| `global_search_expand_units`          | `true`  | Enables [unit expansion](#unit-expansion) on the answer path.      |
| `global_search_expand_max_units`      | `4`     | Units to expand, in rank order.                                    |
| `global_search_expand_per_unit`       | `3`     | Extra passages fetched per expanded unit.                          |
| `global_search_expand_fetch_limit`    | `200`   | Per-collection cap on the expansion fetch.                         |
| `global_search_rerank_results_list`   | `false` | Also reranks the content search result list.                       |
| `global_search_rerank_list_timeout_s` | `2.0`   | Rerank budget for the result list; the answer path uses 4 seconds. |
| `global_search_lane_depth_max`        | `10000` | Upper bound on a lane's depth while it searches for visible rows.  |

## Boundaries

- **The Artemis index** of courses, exercises, exams, FAQs and channels belongs to Artemis. Iris only receives the rows Artemis prefetched from it as entity candidates and never queries it.
- **Authorization** is decided by Artemis. Iris applies the access context and the instance's base URL, but does not know users, enrollments or exam registrations.
- **The Iris course setting** is applied by Artemis, which removes courses with Iris disabled from the answer request. The content search still covers them, because it is search rather than an Iris feature.
- **Continuing an answer in the chat** happens entirely in Artemis, which creates a chat session with the question and the answer. Iris sees it as an ordinary chat on its next message.
