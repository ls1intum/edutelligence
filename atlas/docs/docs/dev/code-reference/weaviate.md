---
title: "Weaviate Integration"
description: "Complete guide to Weaviate vector database integration in AtlasML"
sidebar_position: 7
---

# Weaviate Integration

Weaviate is the vector database powering AtlasML's semantic search and similarity features. This guide covers everything you need to know about how AtlasML integrates with Weaviate.

---

## What is Weaviate?

**Weaviate** is an open-source vector database that stores and searches high-dimensional vectors efficiently.

### Key Features

- **Vector Search**: Find similar items using semantic similarity
- **Hybrid Search**: Combine vector and keyword search
- **GraphQL API**: Flexible query language
- **Scalable**: Handles millions of vectors
- **Schema-Based**: Structured data with properties

### Why AtlasML Uses Weaviate

1. **Semantic Search**: Find similar competencies by meaning, not just keywords
2. **Fast Retrieval**: Sub-100ms queries even with thousands of items
3. **Flexible Schema**: Easy to add new properties without migrations
4. **Vector Storage**: Native support for embeddings
5. **Python SDK**: First-class Python support

---

## Connection Setup

### Environment Variables

Configure Weaviate connection in `.env`:

```bash
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
WEAVIATE_GRPC_PORT=50051
```

### Connection in Code

**File**: `atlasml/clients/weaviate.py`

```python
from atlasml.config import get_settings
import weaviate

settings = get_settings()

client = weaviate.connect_to_local(
    host=settings.weaviate.host,
    port=settings.weaviate.port,
    grpc_port=settings.weaviate.grpc_port
)
```

### Singleton Pattern

AtlasML uses a **singleton** to ensure one client instance:

```python
class WeaviateClientSingleton:
    _instances = {}

    @classmethod
    def get_instance(cls, weaviate_settings=None) -> WeaviateClient:
        if weaviate_settings is None:
            weaviate_settings = get_settings().weaviate

        key = (weaviate_settings.host, weaviate_settings.port)

        if key not in cls._instances:
            cls._instances[key] = WeaviateClient(weaviate_settings)

        return cls._instances[key]
```

**Why singleton?**
- Reuse connection across requests
- Avoid connection overhead
- Thread-safe connection pooling

### Getting the Client

```python
from atlasml.clients.weaviate import get_weaviate_client

client = get_weaviate_client()
```

---

## Collections (Schemas)

### Available Collections

AtlasML defines three main collections:

```python
class CollectionNames(str, Enum):
    EXERCISE = "Exercise"
    COMPETENCY = "Competency"
    SEMANTIC_CLUSTER = "SemanticCluster"
```

### Collection Schemas

#### 1. Competency Collection

```python
COMPETENCY_SCHEMA = {
    "class": "Competency",
    "description": "Competency records with embeddings",
    "vectorizer": "none",  # We provide vectors manually
    "properties": [
        {
            "name": "competency_id",
            "dataType": ["int"],
            "description": "Unique competency ID"
        },
        {
            "name": "title",
            "dataType": ["text"],
            "description": "Competency title"
        },
        {
            "name": "description",
            "dataType": ["text"],
            "description": "Competency description"
        },
        {
            "name": "course_id",
            "dataType": ["int"],
            "description": "Associated course ID"
        }
    ]
}
```

**Example Object**:
```json
{
  "uuid": "a1b2c3d4-...",
  "properties": {
    "competency_id": 42,
    "title": "Object-Oriented Programming",
    "description": "Understanding OOP principles",
    "course_id": 1
  },
  "vector": [0.123, -0.456, 0.789, ...]  // 1536 dimensions
}
```

#### 2. Exercise Collection

```python
EXERCISE_SCHEMA = {
    "class": "Exercise",
    "description": "Exercise records with competency associations",
    "vectorizer": "none",
    "properties": [
        {
            "name": "exercise_id",
            "dataType": ["int"],
            "description": "Unique exercise ID"
        },
        {
            "name": "title",
            "dataType": ["text"],
            "description": "Exercise title"
        },
        {
            "name": "description",
            "dataType": ["text"],
            "description": "Exercise description"
        },
        {
            "name": "competency_ids",
            "dataType": ["int[]"],
            "description": "Associated competency IDs"
        },
        {
            "name": "course_id",
            "dataType": ["int"],
            "description": "Course ID"
        }
    ]
}
```

#### 3. SemanticCluster Collection

```python
SEMANTIC_CLUSTER_SCHEMA = {
    "class": "SemanticCluster",
    "description": "Semantic clusters of competencies",
    "vectorizer": "none",
    "properties": [
        {
            "name": "cluster_id",
            "dataType": ["text"],
            "description": "Unique cluster identifier"
        },
        {
            "name": "course_id",
            "dataType": ["int"],
            "description": "Course ID"
        }
    ]
}
```

### Auto-Creation

Collections are created automatically on startup:

```python
def _ensure_collections_exist(self):
    for collection_name, schema in COLLECTION_SCHEMAS.items():
        if not self.client.collections.exists(collection_name):
            self.client.collections.create_from_dict(schema)
            logger.info(f"✅ Created collection: {collection_name}")
```

---

## CRUD Operations

### Create (Add Embeddings)

Insert a vector with properties:

```python
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

client = get_weaviate_client()

uuid = client.add_embeddings(
    collection_name=CollectionNames.COMPETENCY.value,
    embeddings=[0.1, 0.2, 0.3, ...],  # 1536-dim vector
    properties={
        "competency_id": 100,
        "title": "Machine Learning Basics",
        "description": "Introduction to ML concepts",
        "course_id": 2
    }
)

print(f"Created object: {uuid}")
```

**Returns**: UUID of the created object

**Use Cases**:
- Saving new competencies
- Storing exercise embeddings
- Creating clusters

---

### Read (Get Embeddings)

#### Get by UUID

```python
obj = client.get_embeddings(
    collection_name=CollectionNames.COMPETENCY.value,
    id="a1b2c3d4-..."
)

print(obj["properties"]["title"])
print(obj["vector"][:5])  # First 5 dimensions
```

#### Get All Objects

```python
all_competencies = client.get_all_embeddings(
    collection_name=CollectionNames.COMPETENCY.value
)

for comp in all_competencies:
    print(f"{comp['properties']['competency_id']}: {comp['properties']['title']}")
```

**Returns**: List of objects with vectors and properties

**Use Cases**:
- Exporting data
- Bulk processing
- Analytics

#### Get by Property Filter

```python
course_1_competencies = client.get_embeddings_by_property(
    collection_name=CollectionNames.COMPETENCY.value,
    property_name="course_id",
    property_value=1
)

print(f"Found {len(course_1_competencies)} competencies in course 1")
```

**Use Cases**:
- Filtering by course
- Finding specific competency IDs
- Scoped queries

#### Get by Multiple Properties

```python
results = client.search_by_multiple_properties(
    collection_name=CollectionNames.COMPETENCY.value,
    property_filters={
        "course_id": 1,
        "competency_id": 42
    }
)
```

**Logic**: AND condition (all filters must match)

---

### Update (Modify Properties)

Update an existing object:

```python
success = client.update_property_by_id(
    collection_name=CollectionNames.COMPETENCY.value,
    id="a1b2c3d4-...",
    properties={
        "title": "Updated Title",
        "description": "Updated description"
    },
    vector=[0.5, 0.6, 0.7, ...]  # Optional: update vector too
)

if success:
    print("Update successful")
```

**Parameters**:
- `id`: Object UUID
- `properties`: Properties to update (merged with existing)
- `vector`: Optional new vector

**Use Cases**:
- Updating competency descriptions
- Regenerating embeddings
- Fixing data

---

### Delete (Remove Objects)

Delete by property filter:

```python
deleted_count = client.delete_by_property(
    collection_name=CollectionNames.COMPETENCY.value,
    property_name="competency_id",
    property_value=100
)

print(f"Deleted {deleted_count} objects")
```

**Returns**: Number of deleted objects

**Use Cases**:
- Removing deleted competencies
- Cleaning up test data
- Data synchronization

---

## Vector Search

### Similarity Search

Find similar vectors:

```python
# 1. Generate query embedding
from atlasml.ml.embeddings import EmbeddingGenerator

generator = EmbeddingGenerator()
query_vector = generator.generate_embeddings_openai("Python programming")

# 2. Get all competencies for comparison
competencies = client.get_embeddings_by_property(
    collection_name=CollectionNames.COMPETENCY.value,
    property_name="course_id",
    property_value=1
)

# 3. Compute similarity
from atlasml.ml.similarity_measures import compute_cosine_similarity

results = []
for comp in competencies:
    similarity = compute_cosine_similarity(query_vector, comp["vector"])
    results.append({
        "competency": comp["properties"],
        "similarity": similarity
    })

# 4. Sort by similarity (highest first)
results.sort(key=lambda x: x["similarity"], reverse=True)

# 5. Return top results
top_5 = results[:5]
for r in top_5:
    print(f"{r['competency']['title']}: {r['similarity']:.3f}")
```

**Output**:
```
Python Programming Fundamentals: 0.892
Object-Oriented Programming in Python: 0.845
Data Structures in Python: 0.723
...
```

---

## Schema Management

### Check if Collection Exists

```python
exists = client.client.collections.exists("Competency")
print(f"Competency collection exists: {exists}")
```

### Create Collection

```python
client.client.collections.create_from_dict({
    "class": "MyCollection",
    "vectorizer": "none",
    "properties": [
        {"name": "my_property", "dataType": ["text"]}
    ]
})
```

### Delete Collection

```python
client.delete_all_data_from_collection("Competency")
# Deletes and recreates empty collection
```

### Recreate Collection

```python
client.recreate_collection("Competency")
# Uses schema from COLLECTION_SCHEMAS
```

---

## Connection Lifecycle

### Startup

On application startup (`lifespan` in `app.py`):

```python
@asynccontextmanager
async def lifespan(app):
    # Initialize Weaviate client
    client = get_weaviate_client()

    # Check connection
    if client.is_alive():
        logger.info("🔌 Weaviate: Connected")
    else:
        logger.error("❌ Weaviate: Connection failed")

    # Ensure collections exist
    client._ensure_collections_exist()

    yield  # App is running

    # Shutdown: close connection
    client.close()
```

### Health Check

```python
is_alive = client.is_alive()
# Returns: True if responsive, False otherwise
```

### Close Connection

```python
client.close()
# Releases connection resources
```

---

## Error Handling

### Custom Exceptions

```python
from atlasml.clients.weaviate import (
    WeaviateConnectionError,
    WeaviateOperationError
)
```

#### WeaviateConnectionError

Raised when connection fails:

```python
try:
    client = WeaviateClient(settings)
except WeaviateConnectionError as e:
    logger.error(f"Failed to connect: {e}")
    # Fallback: retry or use cached data
```

#### WeaviateOperationError

Raised when operations fail:

```python
try:
    uuid = client.add_embeddings(...)
except WeaviateOperationError as e:
    logger.error(f"Failed to add embedding: {e}")
    # Handle error: retry, log, notify
```

### Exception Handling Pattern

```python
@router.post("/suggest")
async def suggest_competencies(request: SuggestCompetencyRequest):
    try:
        client = get_weaviate_client()
        results = client.get_embeddings_by_property(...)
        return results
    except WeaviateConnectionError:
        raise HTTPException(503, "Database unavailable")
    except WeaviateOperationError as e:
        logger.error(f"Weaviate error: {e}")
        raise HTTPException(500, "Failed to query database")
```

---

## Performance Considerations

### Query Optimization

1. **Filter Early**: Use property filters to reduce result set
2. **Limit Results**: Don't fetch more than needed
3. **Batch Operations**: Insert multiple objects at once
4. **Connection Pooling**: Reuse client instance (singleton)

### Indexing

Weaviate automatically indexes:
- Vector data (HNSW algorithm)
- Property values (inverted index)

**Query Time**:
- Vector search: O(log n)
- Property filter: O(1) for indexed properties

### Scaling

For large datasets (>1M vectors):
- Use Weaviate clustering
- Optimize `maxConnections` and `efConstruction` in HNSW config
- Consider sharding by course_id

---

## Debugging

### Enable Debug Logging

```python
import logging

logging.getLogger("weaviate").setLevel(logging.DEBUG)
```

### Inspect Collection

```python
collection = client.client.collections.get("Competency")
print(f"Collection: {collection.name}")
print(f"Config: {collection.config}")
```

### Count Objects

```python
competencies = client.get_all_embeddings("Competency")
print(f"Total competencies: {len(competencies)}")
```

### View Sample Object

```python
competencies = client.get_all_embedencies("Competency")
if competencies:
    sample = competencies[0]
    print(f"UUID: {sample['uuid']}")
    print(f"Properties: {sample['properties']}")
    print(f"Vector dimensions: {len(sample['vector'])}")
```

---

## Common Patterns

### Pattern 1: Save Competency with Embedding

```python
def save_competency(competency: Competency):
    # 1. Generate embedding
    generator = EmbeddingGenerator()
    embedding = generator.generate_embeddings_openai(competency.description)

    # 2. Save to Weaviate
    client = get_weaviate_client()
    uuid = client.add_embeddings(
        collection_name=CollectionNames.COMPETENCY.value,
        embeddings=embedding,
        properties={
            "competency_id": competency.id,
            "title": competency.title,
            "description": competency.description,
            "course_id": competency.course_id
        }
    )

    return uuid
```

### Pattern 2: Find Similar Competencies

```python
def find_similar(description: str, course_id: int, top_n: int = 5):
    # 1. Generate query embedding
    generator = EmbeddingGenerator()
    query_embedding = generator.generate_embeddings_openai(description)

    # 2. Get competencies for course
    client = get_weaviate_client()
    competencies = client.get_embeddings_by_property(
        collection_name=CollectionNames.COMPETENCY.value,
        property_name="course_id",
        property_value=course_id
    )

    # 3. Compute similarities
    from atlasml.ml.similarity_measures import compute_cosine_similarity

    results = []
    for comp in competencies:
        similarity = compute_cosine_similarity(query_embedding, comp["vector"])
        results.append((comp, similarity))

    # 4. Sort and return top N
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]
```

### Pattern 3: Batch Insert

```python
def batch_insert_competencies(competencies: list[Competency]):
    generator = EmbeddingGenerator()
    client = get_weaviate_client()

    for comp in competencies:
        embedding = generator.generate_embeddings_openai(comp.description)
        client.add_embeddings(
            collection_name=CollectionNames.COMPETENCY.value,
            embeddings=embedding,
            properties={
                "competency_id": comp.id,
                "title": comp.title,
                "description": comp.description,
                "course_id": comp.course_id
            }
        )
```

---

## Best Practices

### 1. Always Use Property Filters

```python
# ✅ Good - Filter by course_id first
competencies = client.get_embeddings_by_property(
    collection_name="Competency",
    property_name="course_id",
    property_value=1
)

# ❌ Bad - Get all then filter in Python
all_comps = client.get_all_embeddings("Competency")
filtered = [c for c in all_comps if c["properties"]["course_id"] == 1]
```

### 2. Reuse Client Instance

```python
# ✅ Good - Use singleton
client = get_weaviate_client()

# ❌ Bad - Create new instance
client = WeaviateClient()  # Don't do this!
```

### 3. Handle Connection Errors

```python
# ✅ Good - Handle errors
try:
    results = client.get_embeddings_by_property(...)
except WeaviateConnectionError:
    # Fallback or retry
    logger.error("Weaviate unavailable")

# ❌ Bad - Let exception propagate
results = client.get_embeddings_by_property(...)
```

### 4. Use Appropriate Vector Dimensions

```python
# ✅ Good - Consistent dimensions
# OpenAI: 1536 dims, Local model: 384 dims
embedding = generator.generate_embeddings_openai(text)  # 1536

# ❌ Bad - Mixing dimensions
embedding1 = generator.generate_embeddings_openai(text)  # 1536
embedding2 = generator.generate_embeddings(text)         # 384
# Can't compare these!
```

### 5. Clean Up Test Data

```python
# After tests
def cleanup_test_data():
    client = get_weaviate_client()
    client.delete_by_property(
        collection_name="Competency",
        property_name="course_id",
        property_value=999  # Test course ID
    )
```

---

## Next Steps

- **[ML Pipelines](./ml-pipelines.md)**: Learn how embeddings are generated
- **[Modules](./modules.md)**: Deep dive into `weaviate.py` implementation
- **[Troubleshooting](/admin/atlasml-troubleshooting.md)**: Debug Weaviate issues
- **[System Design](../system-design.md)**: Understand Weaviate's role

---

## Resources

- **Weaviate Documentation**: https://weaviate.io/developers/weaviate
- **Python Client**: https://weaviate.io/developers/weaviate/client-libraries/python
- **Vector Search**: https://weaviate.io/developers/weaviate/search/similarity
- **Schema Configuration**: https://weaviate.io/developers/weaviate/config-refs/schema
