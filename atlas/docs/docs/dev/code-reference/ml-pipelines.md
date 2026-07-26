---
title: "ML Pipelines"
description: "Code-grounded AtlasML competency workflows"
sidebar_position: 8
---

# ML Pipelines

AtlasML exposes authenticated competency workflows through `atlasml/routers/competency.py`. Each request creates `PipelineWorkflows`, which ensures the required Weaviate collections exist and then performs the requested operation. This page documents the implementation, not a deployment configuration.

## Storage and embeddings

AtlasML persists competency, exercise, and semantic-cluster records in Weaviate. The workflow vectorizes competency descriptions (falling back to titles) and exercise descriptions before creating or updating those records. Course IDs scope the workflow queries and stored properties.

The current source has the following implementation constraints:

- remote embedding generation calls the source-configured `te-3-small` model identifier and returns its vector;
- the local fallback lazy-loads `sentence-transformers/all-MiniLM-L6-v2`;
- `ModelDimension` defines 1536, 3072, and 384 dimensional constants for the available embedding families; and
- relationship inference constructs a zero-shot NLI pipeline with `facebook/bart-large-mnli` on device `0`.

Those are code-level facts, not statements about deployed credentials, endpoints, hardware capacity, or model assignments. The [Weaviate reference](./weaviate.md) documents the collection client and schema-facing operations.

## Router-to-workflow paths

| Router operation | `PipelineWorkflows` behavior | Stored result |
| --- | --- | --- |
| `POST /api/v1/competency/suggest` | Embeds new text, compares it with course clusters, and falls back to course competency similarity when no clusters exist. | A ranked competency response; no cache is introduced. |
| `POST /api/v1/competency/save` | Creates, updates, or deletes competencies and/or an exercise; competency updates trigger reclustering. | Weaviate competency, exercise, and semantic-cluster records. |
| `GET /api/v1/competency/relations/suggest/{course_id}` | Loads course competency vectors and descriptions, then calculates relation suggestions. | Suggested relations returned to the caller. |
| `POST /api/v1/competency/map-competency-to-exercise` | Adds a competency ID to an existing exercise's stored mapping. | Updated exercise properties. |
| `POST /api/v1/competency/map-competency-to-competency` | Adds reciprocal competency IDs to each stored related-competencies list. | Updated competency properties. |

## Clustering and competency assignment

When competencies are saved or deleted, `recluster_with_new_competencies` loads the course's competency and exercise vectors. If the required data is available and there are no more competencies than exercises, it removes the course's existing semantic-cluster records, applies K-means to exercise embeddings with the competency count as the cluster count, writes new centroids, and assigns each competency to a distinct centroid using cosine similarity.

`new_text_suggestion` embeds the incoming exercise description and compares it with semantic-cluster centroids. It returns the competencies attached to the best clusters. If no clusters exist, `suggest_competencies_if_no_clusters` instead compares the text against the course competency vectors and keeps results at or above the implemented similarity threshold.

## Instructor-feedback centroid updates

The workflow contains an implemented centroid-update path; it is not a generic learning or caching proposal.

- `instructor_feedback_on_new_text` runs after a new exercise with assigned competencies is stored. It adds the exercise embedding to each relevant cluster centroid.
- `instructor_feedback` runs when an existing exercise is updated. It compares the stored competency IDs with the updated IDs. For both removed and newly assigned competencies, it passes the newly generated updated exercise embedding to the centroid helper; it does not retrieve or use the exercise's prior stored vector for removals.
- If an updated exercise has no competencies, `instructor_feedback` returns immediately. Removing the final or all competency assignments therefore does not currently update the old cluster centroids.
- `update_cluster_for_competencies` fetches the competency's assigned cluster and the current number of matching exercises, then calls the addition or removal centroid helper and writes the updated vector to Weaviate.

These updates use current stored competency and cluster data with the generated exercise vector; the source does not implement a separate feedback-history model or a cache.

## Relationship suggestions

`generate_competency_relationship` first filters pairs by cosine similarity. It then applies zero-shot NLI to competency descriptions and produces `MATCH`, `REQUIRE`, `EXTEND`, or `NONE`. `suggest_competency_relations` maps these results to the API's directed relation DTOs. The relation output is a suggestion; persistence remains the caller's responsibility.

AtlasML is an optional external service for its Artemis consumer. Its API and storage implementation should be kept separate from Iris RAG and Memiris memory collections.
