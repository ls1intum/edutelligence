# Source trace for the Iris QA corpus

This trace records the production paths used to derive the scenario matrix and
wire fixtures. It is meant to make corpus updates reviewable when Iris or
Artemis changes.

## Iris production paths

| Concern                              | Source                                                                                                                                        | QA consequence                                                                                                                                                                                                                                                                                                  |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unified chat modes and orchestration | `src/iris/pipeline/chat/chat_pipeline.py`, `src/iris/pipeline/chat/iris_chat_mode.py`                                                         | Four chat modes share one pipeline; mode is a scenario axis.                                                                                                                                                                                                                                                    |
| Support-level policy                 | `src/iris/pipeline/prompts/templates/chat_system_prompt.j2`, `exercise_chat_guide_prompt.j2`                                                  | Every mode is covered at `low`, `moderate`, and `high`; programming output is evaluated after the guide pass and its raw draft is retained. The judge's trusted policy facts include the low-support questions-only rule and its conceptual-question/greeting exceptions, plus the near-soft-due-date 70% rule. |
| Prompt data contract                 | `src/iris/domain/chat/chat_pipeline_execution_dto.py`, `src/iris/domain/pipeline_execution_settings_dto.py`                                   | Scenario payloads parse through the real Pydantic DTO and must round-trip with aliases.                                                                                                                                                                                                                         |
| Persisted message contents           | `src/iris/domain/data/*_message_content_dto.py`, `src/iris/common/message_converters.py`, `src/iris/llm/external/openai_chat.py`, `ollama.py` | Artemis `text`/raw-`json` histories retain every content part and are serialized as model input text; image wire parsing is contract-tested separately.                                                                                                                                                         |
| Agent tools                          | `src/iris/tools/chat_tool_providers.py`, `src/iris/tools/*.py`                                                                                | Required/forbidden tool activities use the production function names.                                                                                                                                                                                                                                           |
| Legacy programming analysis          | `src/iris/pipeline/chat/code_feedback_pipeline.py`, `src/iris/pipeline/prompts/code_feedback_prompt.txt`                                      | The component is constructed but not invoked by the current chat path. Scenarios exercise the live build-log/repository tools and guide; wire this into the suite if production starts calling it.                                                                                                              |
| Current lecture view                 | `src/iris/pipeline/chat/chat_pipeline.py`, `src/iris/domain/data/lecture_context_dto.py`                                                      | Slide, video, and combined-view fixtures include positions and controlled retrieved content.                                                                                                                                                                                                                    |
| Citations                            | `src/iris/pipeline/shared/citation_pipeline.py`, Artemis `iris-content-type.model.ts`                                                         | Lecture and FAQ scenarios check the final seven-field `[cite:L/F:...]` blocks consumed by Artemis, not Markdown links or the pre-enrichment sequence markers.                                                                                                                                                   |
| MCQs                                 | `src/iris/pipeline/chat/mcq_chat_mixin.py`, `src/iris/pipeline/shared/mcq_generation_pipeline.py`, Artemis `iris-content-type.model.ts`       | One-question and multi-question widget contracts are separate hard checks; the evaluator mirrors the delivered payload after Iris strips its internal `source` field.                                                                                                                                           |
| Titles and follow-up suggestions     | `src/iris/pipeline/session_title_generation_pipeline.py`, `src/iris/pipeline/chat/interaction_suggestion_pipeline.py`                         | The production side calls run inside every applicable chat scenario and are included in token accounting.                                                                                                                                                                                                       |
| Tutor suggestions                    | `src/iris/pipeline/tutor_suggestion_pipeline.py`, `src/iris/pipeline/prompts/templates/tutor_suggestion_chat_system_prompt.j2`                | Initial, reply, and regeneration behaviors span low/moderate/high wire settings. The current pipeline does not branch on support level, so they retain behavior-specific rubrics.                                                                                                                               |
| Autonomous tutor                     | `src/iris/pipeline/autonomous_tutor_pipeline.py`, `src/iris/pipeline/prompts/templates/autonomous_tutor_system_prompt.j2`                     | `NO_RESPONSE_NEEDED`, confidence parsing, discussion context, and hidden answers span low/moderate/high wire settings; current prompt code does not branch on that setting.                                                                                                                                     |
| Global search                        | `src/iris/pipeline/global_search_pipeline.py`, `src/iris/pipeline/prompts/global_search_prompts.py`                                           | Grounded answer and navigation/skip paths are separate scenarios.                                                                                                                                                                                                                                               |
| Model request surfaces               | `src/iris/llm/external/openai_chat.py`, `src/iris/pipeline/abstract_agent_pipeline.py`                                                        | The runner constrains Responses and Chat Completions output plus agent iterations at their real request seams, and verifies Azure deployment-to-model metadata before paid execution.                                                                                                                           |

The actual QA worker constructs the production pipeline classes and replaces
only `VectorDatabase`, lecture/FAQ retrieval results, Memiris persistence,
global-search retrieval, and Artemis status delivery. Model calls, prompt
rendering, tools, agents, citations, guide refinement, MCQs, titles, and
suggestions remain production code.

## Artemis source paths

The related Artemis source was traced in `/Users/pat/projects/Artemis` at the
time this corpus was authored, using `develop` commit
`63f981f9dc344b4415d2b5f3018009a5ee3625f9`. Paths below are relative to that
repository. Recheck the record definitions and update this commit marker when
refreshing the corpus against a newer Artemis revision.

| Concern                | Artemis source                                                                                                                                                                                                                    | Wire conclusion                                                                                                                                                                                                              |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chat modes             | `src/main/java/de/tum/cit/aet/artemis/iris/domain/session/IrisChatMode.java`                                                                                                                                                      | Exactly `COURSE_CHAT`, `LECTURE_CHAT`, `PROGRAMMING_EXERCISE_CHAT`, and `TEXT_EXERCISE_CHAT`.                                                                                                                                |
| Support setting        | `.../iris/domain/settings/IrisSupportLevel.java`, `IrisCourseSettings.java`                                                                                                                                                       | JSON values are `low`, `moderate`, and `high`; absent values fall back to `moderate`.                                                                                                                                        |
| Pipeline settings      | `.../iris/service/pyris/dto/PyrisPipelineExecutionSettingsDTO.java`                                                                                                                                                               | Authentication, AI selection, Artemis base URL, variant, support level, and optional streaming flag use camelCase aliases mirrored by fixtures.                                                                              |
| Unified chat body      | `.../iris/service/pyris/dto/chat/PyrisChatPipelineExecutionDTO.java`                                                                                                                                                              | Fixtures use the Java record's exact top-level field names and omit QA metadata before parsing.                                                                                                                              |
| Message contents       | `.../iris/service/pyris/dto/data/PyrisMessageContentBaseDTO.java`, `PyrisTextMessageContentDTO.java`, `PyrisJsonMessageContentDTO.java`, `PyrisImageMessageContentDTO.java`, `PyrisMessageDTO.java`                               | Every persisted history turn has an ID, chronological `sentAt`, and `type`; raw JSON MCQ history round-trips as an object. Image wire parsing is contract-tested, but current `PyrisMessageDTO.of` emits only text and JSON. |
| Programming exercise   | `.../iris/service/pyris/dto/data/PyrisProgrammingExerciseDTO.java`, `PyrisDTOService.java`                                                                                                                                        | Artemis sends template, solution, and test repository maps, but not `recentChanges` or `maxPoints`.                                                                                                                          |
| Programming submission | `.../iris/service/pyris/dto/data/PyrisSubmissionDTO.java`, `IrisChatPipelineExecutionService.java`                                                                                                                                | Artemis sends one selected/latest submission with repository, build state/logs, and latest result. Submission history and uncommitted files are not on the wire.                                                             |
| Proactive events       | `.../iris/domain/settings/event/IrisEventType.java`, `IrisChatSessionService.java`, `PyrisConnectorService.java`                                                                                                                  | Events are lowercase `build_failed` / `progress_stalled` in the `?event=` query, outside the JSON DTO.                                                                                                                       |
| Separate use cases     | `.../iris/service/pyris/dto/chat/tutorsuggestion/PyrisTutorSuggestionPipelineExecutionDTO.java`, `.../dto/autonomoustutor/PyrisAutonomousTutorPipelineExecutionDTO.java`, `.../dto/search/PyrisGlobalSearchAnswerRequestDTO.java` | Tutor suggestion, autonomous tutor, and global search must not be modeled as unified-chat variants.                                                                                                                          |
| Status/activity wire   | `.../iris/web/internal/PyrisInternalStatusUpdateResource.java`, `.../dto/chat/PyrisChatStatusUpdateDTO.java`                                                                                                                      | Local callbacks retain result, terminal state, token usage, activity name/state/order, titles, and suggestions without posting to Artemis.                                                                                   |

(`.../iris/` above expands to
`src/main/java/de/tum/cit/aet/artemis/iris/`.)

This trace exposed that Iris's tutor-suggestion Pydantic DTO inherited the
unified chat DTO and therefore required `chatMode` plus unrelated chat-only
fields that Artemis never sends. This change aligns that DTO with the Artemis
record before using it as a QA contract; the corpus asserts `chatMode` is absent
from tutor-suggestion payloads.

## Drift checks

`iris-qa validate` protects this trace mechanically by:

1. hydrating repository directories into Artemis-shaped `Map<String, String>`
   snapshots;
2. parsing all conversational payloads through the current production Iris
   DTOs and round-tripping aliases and polymorphic message contents, including
   a persisted MCQ JSON object;
3. requiring a final user turn for next-answer chat scenarios;
4. checking all 12 mode/support combinations and all four use-case families,
   plus at least one realistic multi-turn chat in every mode/support cell;
5. verifying fixture size against each scenario's input ceiling;
6. requiring a timezone-aware synthetic clock, unique persisted message IDs,
   and strictly chronological `sentAt` values that freeze prompt and
   deadline-tool time for repeatable weekly execution;
7. verifying programming history chronology, unique submissions, safe UTF-8
   snapshots, and exact repository/date/build agreement with the selected
   Artemis submission; and
8. matching expected activity names to current production tool callables and
   validating every solution-leak oracle before a paid run; and
9. rejecting artifact path escapes, symlinks, invalid UTF-8, inheritance
   cycles, unknown fields, and duplicate scenario IDs.

When an Artemis DTO changes, update the fixture and this trace together. Do not
make the Iris DTO more permissive merely to keep an obsolete scenario passing.
