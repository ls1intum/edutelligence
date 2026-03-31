---
title: 'AtlasML API'
---

# AtlasML API

The AtlasML API is a versioned REST interface exposed via FastAPI. Base paths depend on deployment configuration (e.g., service root when accessed internally). All responses use standard HTTP status codes and Pydantic-validated payloads.

All endpoints are versioned and grouped by router.

## Health

- `GET /api/v1/health/`
  - Returns `200 OK` only when AtlasML can still reach Weaviate, the required collections exist, and a lightweight read succeeds.
  - Returns `503 Service Unavailable` with component details when the service is up but its vector-database dependency is not usable.

## Competency

Authentication: if enabled upstream, include `Authorization: <API_KEY>` with a token present in `ATLAS_API_KEYS`. Unauthorized requests will be rejected by the dependency if configured on the route.

- `POST /api/v1/competency/suggest`

  - Request: `SuggestCompetencyRequest`
  - Response: `SuggestCompetencyResponse`
  - Suggests relevant competencies for a given textual description and course context by leveraging the service’s ML pipeline and vector search. Use this to provide recommendations during content creation or tagging.

- `POST /api/v1/competency/save`

  - Request: `SaveCompetencyRequest`
  - Response: 200 OK (no content)
  - Persists competencies and/or exercises with an explicit `operation_type` (`UPDATE`/`DELETE`). Use this to upsert items or remove outdated entries, triggering downstream updates where applicable.

- `GET /api/v1/competency/relations/suggest/{course_id}`
  - Response: `CompetencyRelationSuggestionResponse`
  - Generates candidate directed relations between competencies for the specified course. This can support graph-building tasks such as prerequisite mapping or curriculum analysis.

See the models page for full schema definitions and field descriptions.
