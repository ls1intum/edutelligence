# Pyris Refactoring: Unified Chat Pipeline

This document describes all breaking changes introduced by the `iris/chore/unify-chat-pipelines` branch that require corresponding changes on the Artemis server side.

---

## 1. Endpoints: 4 → 1

**Old (to be removed):**

- `POST /api/v1/pipelines/course-chat/run`
- `POST /api/v1/pipelines/lecture-chat/run`
- `POST /api/v1/pipelines/programming-exercise-chat/run`
- `POST /api/v1/pipelines/text-exercise-chat/run`

**New:**

- `POST /api/v1/pipelines/chat/run` with a `context` field in the DTO

---

## 2. Unified ChatPipelineExecutionDTO

Artemis must send a single DTO instead of 4 separate ones, with a **new required field `context`**:

```json
{
  "context": "course" | "lecture" | "exercise" | "text_exercise",
  "chat_history": [...],
  "user": {...},
  "course": {...},                            // optional, depending on context
  "exercise": {...},                          // optional
  "lecture": {...},                           // optional
  "programming_exercise_submission": {...},   // optional
  "text_exercise_submission": "...",          // optional
  "metrics": {...},                           // optional
  "event_payload": {...},                     // optional
  "custom_instructions": ""                   // optional
}
```

Artemis populates the relevant fields based on the context — the rest stays `null`.

---

## 3. CourseDTO + ExtendedCourseDTO → Single CourseDTO

`ExtendedCourseDTO` has been deleted. `CourseDTO` now **always** includes the extended fields:

```
exercises: List[ExerciseWithSubmissionsDTO] = []
exams: List[ExamDTO] = []
competencies: List[CompetencyDTO] = []
studentAnalyticsDashboardEnabled: bool = False
```

Artemis must always send the "extended" format.

---

## 4. ExerciseDTO Base Class (new)

`ProgrammingExerciseDTO` and `TextExerciseDTO` now inherit from a shared `ExerciseDTO` base class:

```
ExerciseDTO (new base class)
  - name: str
  - id: int
  - problemStatement: Optional[str]
  - startDate: Optional[datetime]
  - endDate: Optional[datetime]

ProgrammingExerciseDTO(ExerciseDTO)
  - programmingLanguage: Optional[str]
  - templateRepository: Dict[str, str]
  - solutionRepository: Dict[str, str]
  - testRepository: Dict[str, str]
  - maxPoints: Optional[float]
  - recentChanges: Optional[str]

TextExerciseDTO(ExerciseDTO)
  - course: CourseDTO
  - exampleSolution: Optional[str]
```

This is backward-compatible — the fields are the same, only the hierarchy is cleaner.

---

## 5. Status Callback URL: 4 → 1

**Old:**

- `/api/iris/internal/pipelines/course-chat/runs/{id}/status`
- `/api/iris/internal/pipelines/lecture-chat/runs/{id}/status`
- `/api/iris/internal/pipelines/programming-exercise-chat/runs/{id}/status`
- `/api/iris/internal/pipelines/text-exercise-chat/runs/{id}/status`

**New:**

- `/api/iris/internal/pipelines/chat/runs/{id}/status`

Artemis must provide this single endpoint for Iris to send status updates to.

---

## 6. Unified ChatStatusUpdateDTO

Instead of 4 separate status DTOs, there is now a single one:

```
ChatStatusUpdateDTO:
  result: Optional[str]
  session_title: Optional[str]
  suggestions: List[str]
  accessed_memories: List[MemoryDTO]
  created_memories: List[MemoryDTO]
  stages: List[StageDTO]
  tokens: List[TokenUsageDTO]
```

---

## 7. Tool Providers: Context-Based → Data-Based Filtering

Tool providers no longer filter by `ChatContext`. Instead, tools are made available based purely on data availability in the DTO. For example, submission-related tools are only provided when `programming_exercise_submission` is present, regardless of context.

This is an internal Pyris change and does **not** affect Artemis directly.

---

## Summary: Checklist for Artemis

| Task                                         | Breaking?       |
| -------------------------------------------- | --------------- |
| Merge 4 chat endpoints → 1 `/chat/run`       | Yes             |
| Add `context` field to request DTO           | Yes             |
| Replace `ExtendedCourseDTO` with `CourseDTO` | Yes             |
| Unify status callback URL                    | Yes             |
| Unify status response DTO                    | Yes             |
| Introduce `ExerciseDTO` base class           | No (compatible) |
