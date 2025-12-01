---
title: 'Weaviate Integration'
---

# Weaviate Integration

Module: `atlasml/clients/weaviate.py`. The client wraps the official SDK with a singleton accessor, schema bootstrap, and high-level helpers. This keeps API handlers simple and centralizes error handling and connection lifecycle.

:::info Centralized Weaviate Setup
AtlasML connects to the **centralized Weaviate instance** shared by Atlas and Iris microservices. This requires:
- HTTPS connection (`https://your-weaviate-domain.com`)
- API key authentication
- Ports 443 (HTTPS) and 50051 (gRPC)

See the [Weaviate README](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md) for setup instructions.
:::

AtlasML connects to Weaviate using settings from `atlasml/config.py`. On startup, the client ensures that required collections exist with the expected schema, adding missing properties when necessary to avoid manual migrations.

## Collections

- `Exercise`. Stores exercise metadata and optional competency associations for retrieval and analysis.
- `Competency`. Holds core competency records used for suggestions, relations, and clustering operations.
- `SemanticCluster`. Maintains cluster identifiers and related metadata for grouping and labeling.

Properties are defined via `COLLECTION_SCHEMAS` and created/updated at runtime. This allows incremental evolution of the data model without service downtime.

## Client Access

```python
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

client = get_weaviate_client()
items = client.get_all_embeddings(CollectionNames.COMPETENCY.value)
```

## Common Operations

- `add_embeddings(collection, embeddings, properties)` → `uuid`. Inserts a vector and associated properties into a collection and returns the object UUID.
- `get_all_embeddings(collection)` → list of objects with vectors. Iterates all objects for analysis, export, or debugging.
- `get_embeddings_by_property(collection, property_name, property_value)` → filtered list. Fetches objects where a property equals a given value (e.g., `course_id`).
- `search_by_multiple_properties(collection, property_filters)` → filtered list. Combines multiple equality filters (AND) to narrow down results.
- `update_property_by_id(collection, id, properties, vector)` → `True`. Updates stored properties and optionally replaces the vector for a specific UUID.
- `delete_by_property(collection, property_name, property_value)` → number deleted. Removes objects matching the equality filter and reports the count.

Errors raise `WeaviateOperationError`; connectivity issues raise `WeaviateConnectionError`. Callers should translate these into appropriate HTTP responses or retries depending on context.
