import logging
from threading import Thread
from typing import Callable, Sequence
from uuid import UUID

from memiris import (
    LearningService,
    Memory,
    MemoryConnectionService,
    MemoryCreationPipeline,
    MemoryCreationPipelineBuilder,
    MemoryService,
    OllamaService,
)
from memiris.service.vectorizer import Vectorizer
from memiris.util.uuid_util import is_valid_uuid, to_uuid
from weaviate import WeaviateClient

_memiris_embedding_models = ["mxbai-embed-large:latest", "nomic-embed-text:latest"]

_memiris_user_focus_personal_details = """
Find personal details about the user itself.
Always start the content with 'The user'. \
Never call the user by name only use 'the user'. \
The exception would be a learning like 'The user is called John'.
Similarly, use they/them pronouns instead of he/him or she/her. \
The exception would be a learning like 'The user uses she/her pronouns'.
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
Similarly, use they/them pronouns instead of he/him or she/her.
You are encouraged to interpret the text and extract the most relevant information.
You should still focus on the user as a person and not the exact content of the conversation.
In fact the actual content of the conversation is not relevant at all and should not be part of the learnings \
unless they specifically refer to the user.
DO NOT extract how the user is communicating but rather how they expect answers to be communicated to them.
Keep the learnings short and concise. Better have multiple short learnings than one long learning.
"""

_memiris_user_focus_facts = """
Find out what hard facts about the user you can extract from the conversation.
Always start the content with 'The user'.
Never call the user by name only use 'the user'.
Similarly, use they/them pronouns instead of he/him or she/her.
You should not interpret the text but rather extract information that is explicitly stated by the user.
You should focus on the user and not the content of the conversation.
In fact the actual content of the conversation is not relevant at all and should not be part of the learnings \
unless they specifically refer to the user.
Keep the learnings short and concise. Better have multiple short learnings than one long learning.
"""

type Tenant = str


def memiris_create_user_memory_creation_pipeline(
    weaviate_client: WeaviateClient,
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
        MemoryCreationPipelineBuilder(OllamaService())
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_vectorizer(_memiris_embedding_models)
        .add_learning_extractor(focus=_memiris_user_focus_personal_details)
        .add_learning_extractor(focus=_memiris_user_focus_requirements)
        .add_learning_extractor(focus=_memiris_user_focus_facts)
        .add_learning_deduplicator()
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

    def __init__(self, weaviate_client: WeaviateClient, tenant: Tenant):
        self.vectorizer = Vectorizer(_memiris_embedding_models, OllamaService())
        self.memory_creation_pipeline = memiris_create_user_memory_creation_pipeline(
            weaviate_client
        )
        self.learning_service = LearningService(weaviate_client)
        self.memory_service = MemoryService(weaviate_client)
        self.memory_connection_service = MemoryConnectionService(weaviate_client)
        self.tenant = tenant

    def create_memories(self, text: str, reference: str) -> Sequence[Memory]:
        """
        Creates memories for the given text using the memory creation pipeline.

        Args:
            text (str): The text to create memories from.
        """
        return self.memory_creation_pipeline.create_memories(
            self.tenant, text, reference
        )

    def create_memories_in_separate_thread(
        self, text: str, reference: str, result_storage: list[Memory]
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
                memories = self.create_memories(text, reference)
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
