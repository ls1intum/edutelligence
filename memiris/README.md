# Memiris

Memiris is a reusable Python library for long-term LLM memory. It provides generic memory-creation and memory-sleep pipelines, domain objects, vectorization, relationships, and tenant-aware repository abstractions. Consumers choose their own runtime scheduling, model configuration, and HTTP integration.

Iris is one consumer. Its wrapper, agent tools, feature gates, tenants, callbacks, and periodic sleep scheduling are Iris runtime behavior and are documented in the rendered [Iris pipeline system](https://ls1intum.github.io/edutelligence/iris/docs/developer/pipeline-system).

## Core abstractions

- `MemoryCreationPipeline` extracts learnings, deduplicates them, creates memories, vectorizes data, and persists it for a tenant.
- `MemorySleepPipeline` processes a tenant's stored memories and learns/updates memory relationships.
- `LearningRepository`, `MemoryRepository`, and `MemoryConnectionRepository` define tenant-aware storage contracts. The library includes Weaviate-backed implementations.
- `Vectorizer` produces vectors used by repository search and relationship work. Consumers provide the embedding-model implementation(s).
- Builder classes assemble a pipeline from repositories, vectorization, and language-model-backed steps without coupling the library to an application framework.

## Create memories

Configure a creation pipeline with the components required by the application, then invoke it for a tenant and a reference:

```python
from memiris.api.memory_creation_pipeline import MemoryCreationPipelineBuilder

creation_pipeline = (
    MemoryCreationPipelineBuilder()
    .set_learning_repository(learning_repository)
    .set_memory_repository(memory_repository)
    .set_vectorizer(vectorizer)
    .add_learning_extractor(focus=focus, llm_learning_extraction=extractor_llm)
    .add_learning_deduplicator(llm_learning_deduplication=deduplicator_llm)
    .set_memory_creator_langchain(llm=memory_creator_llm)
    .build()
)

memories = creation_pipeline.create_memories(
    tenant="tenant-id",
    text="Conversation or other application text",
    reference="application-reference",
)
```

The tenant is part of the repository operation, not a global process setting. A consumer must derive it from its own authorization and data-isolation model.

## Sleep and relationships

The sleep pipeline requires learning, memory, and memory-connection repositories as well as a vectorizer and its configured language-model steps:

```python
from memiris.api.memory_sleep_pipeline import MemorySleepPipelineBuilder

sleep_pipeline = (
    MemorySleepPipelineBuilder()
    .set_learning_repository(learning_repository)
    .set_memory_repository(memory_repository)
    .set_memory_connection_repository(connection_repository)
    .set_vectorizer(vectorizer)
    .set_tool_llm(tool_llm)
    .set_response_llm(response_llm)
    .build()
)

sleep_pipeline.sleep(tenant="tenant-id")
```

Sleep is a library call; it does not schedule itself. The consumer chooses when and for which authorized tenants to invoke it.

## Repository and vectorization contracts

Repository implementations store and retrieve learnings, memories, and weighted memory connections per tenant. They support the services used by creation, sleep, relationship traversal, and semantic lookup. Weaviate is one provided backend; applications may implement the repository interfaces for another store while retaining the pipeline APIs.

`Vectorizer` accepts the consumer-supplied embedding models and supplies vectors for persisted entities and semantic search. This README intentionally uses generic builder inputs: any application-specific provider, aliases, credentials, and local/cloud routing belong to that consumer's configuration.
