---
title: Domain Models
---

# Domain Models

Iris uses [Pydantic](https://docs.pydantic.dev/) models extensively for request validation, serialization, and data transfer between Artemis and the pipeline system. All domain models live under `src/iris/domain/`.

## DTO Hierarchy

The core DTO hierarchy follows a pattern where pipeline-specific DTOs extend a common base:

```
PipelineExecutionDTO                    # Base for all pipeline executions
├── ChatPipelineExecutionDTO            # Base for chat pipelines
│   ├── ExerciseChatPipelineExecutionDTO
│   ├── CourseChatPipelineExecutionDTO
│   ├── LectureChatPipelineExecutionDTO
│   └── TextExerciseChatPipelineExecutionDTO
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

Extends the base DTO with chat-specific fields:

```python
class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]
```

- **`chat_history`** — The conversation so far, as a list of `PyrisMessage` objects.
- **`user`** — The student's user information (ID, name, language preference).
- **`session_title`** — The current chat session title (may be updated by the pipeline).

### Pipeline-specific Chat DTOs

Each chat pipeline adds its own context fields:

| DTO                                    | Extra Fields                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| `ExerciseChatPipelineExecutionDTO`     | `exercise`, `submission`, `course`, `custom_instructions`                       |
| `CourseChatPipelineExecutionDTO`       | `course` (ExtendedCourseDTO), `metrics`, `event_payload`, `custom_instructions` |
| `LectureChatPipelineExecutionDTO`      | `course`, `lecture` (PyrisLectureDTO), `lecture_unit_id`, `custom_instructions` |
| `TextExerciseChatPipelineExecutionDTO` | `exercise` (TextExerciseDTO), `current_submission`                              |

## Data Models

The `domain/data/` directory contains models representing Artemis entities:

### Course & Exercise Models

| Model                        | File                               | Key Fields                                                 |
| ---------------------------- | ---------------------------------- | ---------------------------------------------------------- |
| `CourseDTO`                  | `course_dto.py`                    | `id`, `name`, `description`                                |
| `ExtendedCourseDTO`          | `extended_course_dto.py`           | Extends CourseDTO with exercises, lectures, FAQs           |
| `ProgrammingExerciseDTO`     | `programming_exercise_dto.py`      | `id`, `title`, `problem_statement`, `programming_language` |
| `TextExerciseDTO`            | `text_exercise_dto.py`             | `id`, `title`, `problem_statement`                         |
| `ExerciseWithSubmissionsDTO` | `exercise_with_submissions_dto.py` | Exercise with submission list                              |

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

| Model           | File                | Purpose                                 |
| --------------- | ------------------- | --------------------------------------- |
| `UserDTO`       | `user_dto.py`       | User information (ID, name, language)   |
| `CompetencyDTO` | `competency_dto.py` | Course competency definition            |
| `FaqDTO`        | `faq_dto.py`        | FAQ question-answer pair                |
| `FeatureDTO`    | `feature_dto.py`    | Variant feature description for Artemis |

## Data Flow

The typical data flow for a chat pipeline request:

```
Artemis (JSON) → FastAPI validates → DTO object → Pipeline.__call__(dto, variant, callback)
                                                          │
                                                          ├── dto.chat_history → message_history
                                                          ├── dto.exercise → tool context
                                                          ├── dto.submission → tool context
                                                          └── dto.course → tool context
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
    sender: IrisMessageRole      # USER, ASSISTANT, SYSTEM
    contents: list[MessageContentDTO]  # Text, image, tool call, etc.
```

Messages are converted to LangChain format for the agent loop using `convert_iris_message_to_langchain_message()` from `common/message_converters.py`.
