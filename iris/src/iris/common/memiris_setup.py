import logging
import os
from threading import Thread
from typing import Callable, Sequence
from uuid import UUID

from memiris import (
    LearningDTO,
    LearningService,
    Memory,
    MemoryConnectionDTO,
    MemoryConnectionService,
    MemoryCreationPipeline,
    MemoryCreationPipelineBuilder,
    MemoryDTO,
    MemoryService,
    MemoryWithRelationsDTO,
    OllamaLanguageModel,
)
from memiris.service.vectorizer import Vectorizer
from memiris.util.uuid_util import is_valid_uuid, to_uuid
from weaviate import WeaviateClient

from iris.llm import OllamaModel
from iris.llm.llm_manager import LlmManager

_memiris_user_focus_personal_details = """
Find personal details about the user itself.
Always start the content with 'The user'. \
Never call the user by name only use 'the user'.
Think about the meaning of the user's text and not just the words.
You are encouraged to interpret the text and extract the most relevant information.
You should still focus on the user as a person and not the exact content of the conversation.
In fact the actual content of the conversation is not relevant at all and should not be part of the learnings \
unless they specifically refer to the user.
Keep the learnings short and concise. Better have multiple short learnings than one long learning.
"""

_memiris_user_focus_requirements = """
Find out what requirements the user has for answers to their questions.
Always start the content with 'The user'. \
Never call the user by name only use 'the user'.
You are encouraged to interpret the text and extract the most relevant information.
You should still focus on the user as a person and not the exact content of the conversation.
In fact the actual content of the conversation is not relevant at all and should not be part of the learnings \
unless they specifically refer to the user.
Keep the learnings short and concise. Better have multiple short learnings than one long learning.
"""

_memiris_user_focus_facts = """
Find out what hard facts about the user you can extract from the conversation.
Always start the content with 'The user'.
Never call the user by name only use 'the user'.
You should not interpret the text but rather extract information that is explicitly stated by the user.
You should focus on the user and not the content of the conversation.
In fact the actual content of the conversation is not relevant at all and should not be part of the learnings \
unless they specifically refer to the user.
Keep the learnings short and concise. Better have multiple short learnings than one long learning.
"""

type Tenant = str


def setup_ollama_env_vars():
    llm_manager = LlmManager()
    iris_ollama_model: OllamaModel | None = None
    for model in llm_manager.entries:
        if isinstance(model, OllamaModel):
            iris_ollama_model = model
            break

    if iris_ollama_model is not None:
        os.environ["OLLAMA_HOST"] = iris_ollama_model.host
        os.environ["OLLAMA_TOKEN"] = iris_ollama_model.api_key or ""

    if not os.environ.get("OLLAMA_HOST"):
        raise RuntimeError("Ollama host not configured for Memiris LLM access.")
    if not os.environ.get("OLLAMA_TOKEN"):
        raise RuntimeError("Ollama token not configured for Memiris LLM access.")


def memiris_create_user_memory_creation_pipeline_ollama(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemoryCreationPipeline:
    """
    Creates a memory creation pipeline for users.

    This function initializes and configures a memory creation pipeline for users.
    It sets up LLM access and vector database access.
    It also adds learning extractors for personal details, requirements, and facts about the user.

    Parameters:
        weaviate_client (WeaviateClient): A client instance for interacting with the Weaviate database.

    Returns:
        MemoryCreationPipeline: The fully constructed memory creation pipeline.
    """
    return (
        MemoryCreationPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .add_learning_extractor(focus=_memiris_user_focus_personal_details)
        .add_learning_extractor(focus=_memiris_user_focus_requirements)
        .add_learning_extractor(focus=_memiris_user_focus_facts)
        .add_learning_deduplicator()
        .set_memory_creator_langchain()
        .build()
    )


def get_tenant_for_user(user_id: int) -> Tenant:
    """
    Returns the tenant for the given user ID.

    Args:
        user_id (number): The ID of the user.
    Returns:
        Tenant: The tenant string for the user.
    """
    return f"artemis-user-{user_id}"


def has_memories_for_tenant(tenant: Tenant, memory_service: MemoryService) -> bool:
    """
    Checks if there are any memories for the given tenant.

    Args:
        tenant (Tenant): The tenant to check for memories.
        memory_service (MemoryService): The service to interact with memory storage.

    Returns:
        bool: True if there are memories for the tenant, False otherwise.
    """
    try:
        return len(memory_service.get_all_memories(tenant)) > 0
    except Exception as e:
        logging.error(
            "Error checking memories for tenant %s: %s", tenant, e, exc_info=True
        )
        return False


class MemirisWrapper:
    """
    A wrapper class for the Memiris memory service for easier use in Iris's pipelines.
    """

    enabled: bool

    def __init__(self, weaviate_client: WeaviateClient, tenant: Tenant):
        try:
            setup_ollama_env_vars()
        except RuntimeError:
            logging.error(
                "Failed to setup Memiris. Please provide at least one Ollama model in the LLM config"
            )
            self.enabled = False
            return
        self.enabled = True
        self._memiris_embedding_models = [
            OllamaLanguageModel("mxbai-embed-large:latest"),
            OllamaLanguageModel("nomic-embed-text:latest"),
            # OllamaLanguageModel("embeddinggemma:latest"),
            # OllamaLanguageModel("qwen3-embedding:0.6b"),
        ]
        self.vectorizer = Vectorizer(self._memiris_embedding_models)
        self.memory_creation_pipeline = (
            memiris_create_user_memory_creation_pipeline_ollama(
                weaviate_client, self.vectorizer
            )
        )
        self.learning_service = LearningService(weaviate_client)
        self.memory_service = MemoryService(weaviate_client)
        self.memory_connection_service = MemoryConnectionService(weaviate_client)
        self.tenant = tenant

    def create_memories(self, text: str) -> Sequence[Memory]:
        """
        Creates memories for the given text using the memory creation pipeline.

        Args:
            text (str): The text to create memories from.
        """
        return self.memory_creation_pipeline.create_memories(self.tenant, text)

    def create_memories_in_separate_thread(
        self, text: str, result_storage: list[Memory]
    ) -> Thread:
        """
        Creates memories for the given text in a separate thread and stores the results in the provided storage.

        Args:
            text (str): The text to create memories from.
            result_storage (list[Memory]): The storage to append the created memories to.
        Returns:
            Thread: The thread that is running the memory creation.
        """

        def _create_memories():
            try:
                memories = self.create_memories(text)
                result_storage.extend(memories)
            except Exception as e:
                logging.error(
                    "Failed to create memories in thread: %s", e, exc_info=True
                )

        thread = Thread(name="MemirisMemoryCreationThread", target=_create_memories)
        thread.start()
        return thread

    def has_memories(self) -> bool:
        """
        Checks if there are any memories for the tenant.

        Returns:
            bool: True if there are memories, False otherwise.
        """
        return has_memories_for_tenant(self.tenant, self.memory_service)

    def create_tool_memory_search(
        self, accessed_memory_storage: list[Memory], limit: int = 5
    ) -> Callable[[str], Sequence[Memory] | str]:
        """
        Creates a tool for vector search in the memory service.

        Returns:
            Callable[[str], Any]: A function that performs vector search.
        """

        def memiris_search_for_memories(query: str) -> Sequence[Memory] | str:
            """
            Use this tool to search for memories about a user.
            This function performs a semantic search for memories that match the query.
            Only use this tool to search for new memories, not to find similar memories.
            The query can be a natural language question or statement.

            Args:
                query (str): The query string to search for memories.
            Returns:
                Sequence[Memory]: A list of Memory objects that most closely match the query.
            """
            vectors = self.vectorizer.vectorize(query)
            memories = self.memory_service.semantic_search(
                tenant=self.tenant, vectors=vectors, limit=limit
            )
            accessed_memory_storage.extend(memories)
            if len(memories) == 0:
                return "No memories found for the given query."

            return memories

        return memiris_search_for_memories

    def create_tool_find_similar_memories(
        self, accessed_memory_storage: list[Memory], limit: int = 5
    ) -> Callable[[str], Sequence[Memory] | str]:
        """
        Creates a tool to find similar memories based on a given memory ID.

        Returns:
            Callable[[str], Sequence[Memory]]: A function that finds similar memories.
        """

        def memiris_find_similar_memories(memory_id: str) -> Sequence[Memory] | str:
            """
            Use this tool to find similar memories of another memory.
            You must provide the valid UUID of the memory you want to find similar memories for.
            UNDER NO CIRCUMSTANCES GUESS THE UUID. Always use the correct ids as provided by previous tools.
            If you consider a memory interesting, you should use this tool to find similar memories.
            This will return a list of the most similar memories to the one you provided.
            If you do not provide a valid UUID, the tool will return an error message.

            Args:
                memory_id (str): The valid UUID of the memory to find similar memories for.
            Returns:
                Sequence[Memory] | str: A list of Memory objects that are similar to the provided memory ID,
                or an error message.
            """
            if is_valid_uuid(memory_id):
                memory_uuid: UUID = to_uuid(memory_id)  # type: ignore
            else:
                return "Invalid memory ID provided. Please provide a valid UUID."

            memory = self.memory_service.get_memory_by_id(self.tenant, memory_uuid)

            if memory is None:
                return f"Memory with ID {memory_uuid} not found. Please provide a valid memory ID."

            memories: list[Memory] = []

            if memory.connections:
                connections = (
                    self.memory_connection_service.get_memory_connections_by_ids(
                        self.tenant, memory.connections
                    )
                )
                memory_ids: list[UUID] = []
                for connection in sorted(
                    connections, key=lambda x: x.weight, reverse=True
                ):
                    for mid in connection.memories:
                        if mid not in memory_ids:
                            memory_ids.append(mid)

                if len(memory_ids) > limit:
                    memory_ids = memory_ids[:limit]

                memories.extend(
                    self.memory_service.get_memories_by_ids(self.tenant, memory_ids)
                )

                if len(memories) == limit:
                    accessed_memory_storage.extend(memories)
                    return memories

            memories.extend(
                self.memory_service.semantic_search(
                    tenant=self.tenant,
                    vectors=memory.vectors,
                    limit=limit - len(memories),
                )
            )

            accessed_memory_storage.extend(memories)
            return memories

        return memiris_find_similar_memories

    def get_memory_with_relations(
        self, memory_id: UUID | str
    ) -> MemoryWithRelationsDTO | None:
        """
        Fetch a memory by ID and fully populate its learnings and connections.

        Returns a MemoryWithRelationsDTO or None if the memory does not exist.
        """
        if isinstance(memory_id, str):
            if not is_valid_uuid(memory_id):
                return None
            memory_uuid: UUID = to_uuid(memory_id)  # type: ignore
        else:
            memory_uuid = memory_id

        memory = self.memory_service.get_memory_by_id(self.tenant, memory_uuid)
        if memory is None:
            return None

        # Fetch learnings
        learning_ids = memory.learnings
        learnings = (
            self.learning_service.get_learnings_by_ids(self.tenant, learning_ids)
            if learning_ids
            else []
        )

        # Fetch connections and all connected memories
        connections = (
            self.memory_connection_service.get_memory_connections_by_ids(
                self.tenant, memory.connections
            )
            if memory.connections
            else []
        )

        connected_memory_ids: list[UUID] = []
        for conn in connections:
            for mid in conn.memories:
                if mid not in connected_memory_ids:
                    connected_memory_ids.append(mid)

        connected_memories = (
            self.memory_service.get_memories_by_ids(self.tenant, connected_memory_ids)
            if connected_memory_ids
            else []
        )
        connected_memory_map: dict[UUID, Memory] = {
            memory.id: memory for memory in connected_memories if memory.id is not None
        }

        # Build DTOs
        memory_dto = MemoryDTO.from_memory(memory)
        learning_dtos = [LearningDTO.from_learning(learning) for learning in learnings]

        connection_dtos = []
        for conn in connections:
            cm = [
                MemoryDTO.from_memory(connected_memory_map[mid])
                for mid in conn.memories
                if mid in connected_memory_map
            ]
            connection_dtos.append(MemoryConnectionDTO.from_connection(conn, cm))

        return MemoryWithRelationsDTO(
            memory=memory_dto, learnings=learning_dtos, connections=connection_dtos
        )
