---
title: 'AtlasML Models'
---

# AtlasML Models

Module: `atlasml/models/competency.py`. These Pydantic models define the API contracts and core DTOs. They are validated automatically by FastAPI and rendered in OpenAPI, enabling type-safe client generation and consistent error handling.

## Core Types

- `OperationType`: `UPDATE` | `DELETE`. Indicates whether a request should upsert or remove records. Use `UPDATE` for both creating and modifying entries.

- `Competency`. Represents a single competency item identified within a course. It is the core unit for suggestions, relations, and persistence.

  - `id: int`
  - `title: str`
  - `description: Optional[str]`
  - `course_id: int`

- `ExerciseWithCompetencies`. Captures an exercise artifact and optional competency links. Useful when associating learning content with one or more competencies.

  - `id: int`
  - `title: str`
  - `description: str`
  - `competencies: Optional[list[int]]`
  - `course_id: int`

- `SemanticCluster`. Describes a group identifier, its course context, and a vector embedding. This can support clustering and labeling workflows.
  - `cluster_id: str`
  - `course_id: int`
  - `vector_embedding: list[float]`

## Request/Response DTOs

- `SuggestCompetencyRequest`. Input payload for retrieving recommended competencies. Provide a natural-language `description` and the `course_id` for contextualization.

  - `description: str`
  - `course_id: int`

- `SuggestCompetencyResponse`. Output with a ranked list of `Competency` objects. Consumers can display, filter, or post-process suggestions as needed.

  - `competencies: list[Competency]`

- `SaveCompetencyRequest`. Wrapper for saving either a list of competencies, a single exercise, or both, along with an `operation_type`. This unifies create/update/delete behaviors behind a single endpoint.

  - `competencies: Optional[list[Competency]]`
  - `exercise: Optional[ExerciseWithCompetencies]`
  - `operation_type: OperationType`

- `RelationType`: `MATCHES` | `EXTENDS` | `REQUIRES`. Encodes the semantics of edges in a competency graph (e.g., prerequisites or hierarchical relationships).

- `CompetencyRelation`. Directed edge from `tail_id` to `head_id` with an associated `relation_type`. Used to represent candidate or curated links among competencies.

  - `tail_id: int`
  - `head_id: int`
  - `relation_type: RelationType`

- `CompetencyRelationSuggestionResponse`. Collection of proposed relations for a course. Downstream systems may visualize, validate, or persist these links.
