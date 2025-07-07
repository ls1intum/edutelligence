# Memiris

Memiris is a Python library to equip large language models (LLMs) with a sophisticated long-term memory system.

## Usage

Memiris provides a set of pipelines to create memories and run the sleep functionality.
All pipelines are built using Builder classes, which allow you to customize the components used in the pipeline.

### Memory Creation

To create memories from a text input, you can use the `MemoryCreationPipeline`, which is built using the `MemoryCreationPipelineBuilder`.
In the builder, you can add the following components:

- Learning Extractors: These extract relevant learnings from the text input.
- Learning Deduplicator: This component ensures that duplicate learnings are removed.
- Memory Creator: This component creates the memory from the extracted learnings.
- Learning Repository: This is where the learnings are stored. Can either be a Weaviate client or an implementation of the `LearningRepository` interface.
- Memory Repository: This is where the memories are stored. Can either be a Weaviate client or an implementation of the `MemoryRepository` interface.
- Vectorizer: This component is used to vectorize the learnings and memories. You can specify multiple embedding models. Can either be a list of model names or an implementation of the `Vectorizer` interface.

Once the pipeline is built, you can call the `create_memories` method with a tenant identifier and text input to create memories.

```python
from memiris import MemoryCreationPipelineBuilder, MemoryCreationPipeline, OllamaService, Memory
from weaviate import WeaviateClient

ollama_service: OllamaService
weaviate_client: WeaviateClient

pipeline: MemoryCreationPipeline = MemoryCreationPipelineBuilder(ollama_service) \
    .add_learning_extractor("Find details about the user itself. [...]") \
    .add_learning_extractor("Find details about the user's preferences. [...]") \
    .add_learning_deduplicator() \
    .set_memory_creator() \
    .set_learning_repository(weaviate_client) \
    .set_memory_repository(weaviate_client) \
    .set_vectorizer(["mxbai-embed-large:latest", "nomic-embed-text:latest"]) \
    .build()

memories: list[Memory] = pipeline.create_memories("user_id", "Hello, my name is John Doe. I love hiking and photography. [...]")
```

### Sleep Pipeline

To run the sleep functionality, you can use the `MemorySleepPipeline`, which is built using the `MemorySleepPipelineBuilder`.
In the builder, you can add the following components:

- Learning Repository: This is where the learnings are stored. Can either be a Weaviate client or an implementation of the `LearningRepository` interface.
- Memory Repository: This is where the memories are stored. Can either be a Weaviate client or an implementation of the `MemoryRepository` interface.
- Memory Connection Repository: This is where the connections between memories are stored. Can either be a Weaviate client or an implementation of the `MemoryConnectionRepository` interface.
- Vectorizer: This component is used to vectorize the learnings and memories. You can specify multiple embedding models. Can either be a list of model names or an implementation of the `Vectorizer` interface.

You can then call the `sleep` method with a tenant identifier to run the sleep functionality for that tenant.

```python
from memiris import MemorySleepPipelineBuilder, MemorySleepPipeline, OllamaService
from weaviate import WeaviateClient

ollama_service: OllamaService
weaviate_client: WeaviateClient

pipeline: MemorySleepPipeline = MemorySleepPipelineBuilder(ollama_service) \
    .set_learning_repository(weaviate_client) \
    .set_memory_repository(weaviate_client) \
    .set_memory_connection_repository(weaviate_client) \
    .set_vectorizer(["mxbai-embed-large:latest", "nomic-embed-text:latest"]) \
    .build()

pipeline.sleep("user_id")
```
