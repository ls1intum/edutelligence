---
title: Domain Models
---

# Domain Models

Iris uses [Pydantic](https://docs.pydantic.dev/) models extensively for request validation, serialization, and data transfer between Artemis and the pipeline system. All domain models live under `src/iris/domain/`.

## DTO Hierarchy

The core DTO hierarchy follows a pattern where pipeline-specific DTOs extend a common base:

```
PipelineExecutionDTO                    # Base for all pipeline executions
├── ChatPipelineExecutionDTO            # Every student chat, in every chat mode
├── IngestionPipelineExecutionDto       # Base for ingestion pipelines
├── CompetencyExtractionPipelineExecutionDTO
├── InconsistencyCheckPipelineExecutionDTO
├── RewritingPipelineExecutionDTO
└── ...
```

### `PipelineExecutionDTO`

The base DTO that all pipeline execution requests extend:

```python
class PipelineExecutionDTO(BaseModel):
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[list[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
```

- **`settings`** — Contains the Artemis base URL, authentication token, and variant selection.
- **`initial_stages`** — Pipeline execution stages for progress tracking.

### `PipelineExecutionSettingsDTO`

Carries execution context from Artemis:

```python
class PipelineExecutionSettingsDTO(BaseModel):
    authentication_token: str = Field(alias="authenticationToken")
    artemis_llm_selection: str = Field(alias="selection", default="CLOUD_AI")
    artemis_base_url: str = Field(alias="artemisBaseUrl")
    variant: str = Field(default="default")
```

- `artemis_base_url` — The URL of the Artemis instance making the request.
- `authentication_token` — Used for callbacks to Artemis and as a run/session ID.
- `variant` — The variant ID to use (defaults to `"default"`).
- `artemis_llm_selection` — Either `"CLOUD_AI"` or `"LOCAL_AI"`, controls cloud vs. local model selection.

### `ChatPipelineExecutionDTO`

The request body of `POST /chat/run`. It carries the chat itself, the course, and the entity fields for whichever context is active:

```python
class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    chat_mode: IrisChatMode = Field(alias="chatMode")
    user: UserDTO
    course: CourseDTO

    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    metrics: Optional[StudentMetricsDTO] = None
    custom_instructions: Optional[str] = Field(alias="customInstructions", default="")

    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        alias="programmingExercise", default=None
    )
    text_exercise: Optional[TextExerciseDTO] = Field(alias="textExercise", default=None)
    lecture: Optional[PyrisLectureDTO] = None
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
    context: Optional[List[LectureContextDTO]] = None
    programming_exercise_submission: Optional[ProgrammingSubmissionDTO] = Field(
        alias="programmingExerciseSubmission", default=None
    )
    text_exercise_submission: str = Field(alias="textExerciseSubmission", default="")
```

- **`chat_mode`** — The active context of the chat. Determines which entity fields Artemis populates.
- **`chat_history`** — The conversation so far, as a list of `PyrisMessage` objects.
- **`user`** — The student's user information (ID, name, language preference, Memiris opt-in).
- **`course`** — Always present, in every mode. Carries the course exercises, lectures, competencies and FAQs.
- **`session_title`** — The current chat title (may be updated by the pipeline).
- **`context`** — What the student is currently looking at on a lecture page (video, slides, combined view). A `model_validator` derives `lecture_unit_id` from a combined-view entry when the field is not set explicitly, which scopes RAG retrieval to that lecture unit.

### Fields per Chat Mode

The entity fields are all optional because a request only carries the ones its mode needs:

| `chat_mode`                 | Populated entity fields                                             |
| --------------------------- | ------------------------------------------------------------------- |
| `COURSE_CHAT`               | `course`, `metrics`                                                 |
| `LECTURE_CHAT`              | `course`, `lecture`, optionally `lecture_unit_id` and `context`     |
| `PROGRAMMING_EXERCISE_CHAT` | `course`, `programming_exercise`, `programming_exercise_submission` |
| `TEXT_EXERCISE_CHAT`        | `course`, `text_exercise`, `text_exercise_submission`               |

### Pipeline-specific Chat DTOs

### `IrisChatMode`

```python
class IrisChatMode(StrEnum):
    COURSE = "COURSE_CHAT"
    LECTURE = "LECTURE_CHAT"
    EXERCISE = "PROGRAMMING_EXERCISE_CHAT"
    TEXT_EXERCISE = "TEXT_EXERCISE_CHAT"
```

The string values mirror the `IrisChatMode` enum on the Artemis side and reach Iris as the `chatMode` field. Changing a value is a breaking change that both services have to make together.

## Data Models

The `domain/data/` directory contains models representing Artemis entities:

### Course & Exercise Models

| Model                        | File                               | Key Fields                                                                                   |
| ---------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------- |
| `CourseDTO`                  | `course_dto.py`                    | `id`, `name`, `description`, `exercises`, `lectures`, `exams`, `competencies`, course policy |
| `ProgrammingExerciseDTO`     | `programming_exercise_dto.py`      | `id`, `title`, `problem_statement`, `programming_language`                                   |
| `TextExerciseDTO`            | `text_exercise_dto.py`             | `id`, `title`, `problem_statement`                                                           |
| `ExerciseWithSubmissionsDTO` | `exercise_with_submissions_dto.py` | Exercise with submission list, used inside `CourseDTO.exercises`                             |

### Submission & Feedback Models

| Model                      | File                            | Key Fields                                            |
| -------------------------- | ------------------------------- | ----------------------------------------------------- |
| `ProgrammingSubmissionDTO` | `programming_submission_dto.py` | `date`, `repository`, `build_failed`, `latest_result` |
| `SimpleSubmissionDTO`      | `simple_submission_dto.py`      | Lightweight submission representation                 |
| `ResultDTO`                | `result_dto.py`                 | Test results, score, feedbacks                        |
| `FeedbackDTO`              | `feedback_dto.py`               | Individual test feedback with detail text             |
| `BuildLogEntry`            | `build_log_entry.py`            | Build/compilation log entries                         |

### Lecture Models

| Model                 | File                        | Key Fields                    |
| --------------------- | --------------------------- | ----------------------------- |
| `PyrisLectureDTO`     | `lecture_dto.py`            | `id`, `title`, `units`        |
| `PyrisLectureUnitDTO` | `pyris_lecture_unit_dto.py` | Lecture unit with content     |
| `LectureUnitPageDTO`  | `lecture_unit_page_dto.py`  | Single page of a lecture unit |

### Message Models

| Model                    | File                           | Purpose                    |
| ------------------------ | ------------------------------ | -------------------------- |
| `TextMessageContentDTO`  | `text_message_content_dto.py`  | Text content in a message  |
| `ImageMessageContentDTO` | `image_message_content_dto.py` | Image content in a message |
| `JsonMessageContentDTO`  | `json_message_content_dto.py`  | JSON content in a message  |
| `ToolCallDTO`            | `tool_call_dto.py`             | Tool call representation   |
| `ToolMessageContentDTO`  | `tool_message_content_dto.py`  | Tool result message        |

### Other Models

| Model           | File                | Purpose                                   |
| --------------- | ------------------- | ----------------------------------------- |
| `UserDTO`       | `user_dto.py`       | `id`, name, `lang_key`, `memiris_enabled` |
| `CompetencyDTO` | `competency_dto.py` | Course competency definition              |
| `FaqDTO`        | `faq_dto.py`        | FAQ question-answer pair                  |
| `FeatureDTO`    | `feature_dto.py`    | Variant feature description for Artemis   |

## Data Flow

The typical data flow for a chat pipeline request:

```
Artemis (JSON) → FastAPI validates → DTO object → Pipeline.__call__(dto, variant, callback)
                                                          │
                                                          ├── dto.chat_mode → prompt blocks, tool gating
                                                          ├── dto.chat_history → message_history
                                                          ├── dto.course → tool context
                                                          ├── dto.programming_exercise → tool context
                                                          ├── dto.programming_exercise_submission → tool context
                                                          └── dto.lecture → retrieval scope
```

1. **Artemis sends JSON** — Serialized with camelCase field names.
2. **FastAPI deserializes** — Pydantic validates and converts to the DTO using field aliases.
3. **Pipeline reads DTO** — Extracts chat history, user info, and domain-specific context.
4. **Tools read DTO fields** — Exercise data, submissions, etc. are passed to tool factory functions.
5. **Response via callback** — Results are sent back to Artemis through the `StatusCallback`.

## Pydantic Conventions

Iris DTOs follow these conventions:

- **Field aliases** — Artemis sends camelCase JSON; DTOs use snake_case with `alias="camelCase"`:

  ```python
  chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
  ```

- **`populate_by_name = True`** — Models accept both the alias and the Python name:

  ```python
  class Config:
      populate_by_name = True
  ```

- **Optional fields** — Most fields are `Optional` with defaults, since Artemis may not always provide all data.

- **Validation** — Pydantic v2 validators are used for complex validation (see `config.py` for an example with `model_validator`).

## PyrisMessage

The shared message format used across all pipelines:

```python
class PyrisMessage(BaseModel):
    sender: IrisMessageRole
    contents: list[MessageContentDTO]  # Text, image, tool call, etc.


class IrisMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "LLM"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"
    ARTIFACT = "ARTIFACT"
```

Messages are converted to LangChain format for the agent loop using `convert_iris_message_to_langchain_message()` from `common/message_converters.py`.
