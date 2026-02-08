import logging
import time
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
from memiris.api.memory_sleep_pipeline import (
    MemorySleepPipeline,
    MemorySleepPipelineBuilder,
)
from memiris.llm.openai_language_model import OpenAiLanguageModel
from memiris.service.vectorizer import Vectorizer
from memiris.util.uuid_util import is_valid_uuid, to_uuid
from weaviate import WeaviateClient

from iris.config import settings
from iris.llm import AzureOpenAIChatModel, OllamaModel
from iris.llm.external.openai_chat import OpenAIChatModel
from iris.llm.llm_manager import LlmManager
from iris.tracing import get_current_context, observe, set_current_context
from iris.vector_database.database import VectorDatabase

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


def _convert_iris_model_to_memiris_llm(
    model_id: str,
) -> OpenAiLanguageModel | OllamaLanguageModel:
    """
    Convert an Iris LLM model ID to a Memiris-compatible language model.

    Args:
        model_id: The ID of the model from the LLM configuration.

    Returns:
        A Memiris-compatible language model (OpenAiLanguageModel or OllamaLanguageModel).

    Raises:
        ValueError: If the model cannot be found or is not a supported type.
    """
    llm_manager = LlmManager()
    model = llm_manager.get_llm_by_id(model_id)

    if model is None:
        raise ValueError(f"Model with ID '{model_id}' not found in LlmManager")

    if isinstance(model, OllamaModel):
        return OllamaLanguageModel(model.model, model.host, model.api_key)
    elif isinstance(model, (OpenAIChatModel, AzureOpenAIChatModel)):
        return OpenAiLanguageModel(
            model=model.model,
            api_key=model.api_key,
            azure=isinstance(model, AzureOpenAIChatModel),
            azure_endpoint=getattr(model, "endpoint", None),
            api_version=getattr(model, "api_version", None),
        )
    else:
        raise ValueError(
            f"Model type '{type(model).__name__}' is not supported for Memiris"
        )


def _create_memory_creation_pipeline(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemoryCreationPipeline:
    """
    Creates a memory creation pipeline for users using configured LLMs.

    Args:
        weaviate_client: A client instance for interacting with the Weaviate database.
        vectorizer: The vectorizer to use for embedding generation.

    Returns:
        MemoryCreationPipeline: The fully constructed memory creation pipeline.
    """
    if not settings.memiris.llm_configuration:
        raise ValueError("Memiris LLM configuration is not set")

    config = settings.memiris.llm_configuration

    learning_extractor_llm = _convert_iris_model_to_memiris_llm(
        config.learning_extractor
    )
    learning_deduplicator_llm = _convert_iris_model_to_memiris_llm(
        config.learning_deduplicator
    )
    memory_creator_llm = _convert_iris_model_to_memiris_llm(config.memory_creator)

    return (
        MemoryCreationPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .add_learning_extractor(
            focus=_memiris_user_focus_personal_details,
            llm_learning_extraction=learning_extractor_llm,
        )
        .add_learning_extractor(
            focus=_memiris_user_focus_requirements,
            llm_learning_extraction=learning_extractor_llm,
        )
        .add_learning_extractor(
            focus=_memiris_user_focus_facts,
            llm_learning_extraction=learning_extractor_llm,
        )
        .add_learning_deduplicator(llm_learning_deduplication=learning_deduplicator_llm)
        .set_memory_creator_langchain(llm=memory_creator_llm)
        .build()
    )


def _create_memory_sleep_pipeline(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemorySleepPipeline:
    """
    Creates a memory sleep pipeline for users using configured LLMs.

    Args:
        weaviate_client: A client instance for interacting with the Weaviate database.
        vectorizer: The vectorizer to use for embedding generation.

    Returns:
        MemorySleepPipeline: The fully constructed memory sleep pipeline.
    """
    if not settings.memiris.llm_configuration:
        raise ValueError("Memiris LLM configuration is not set")

    config = settings.memiris.llm_configuration

    tool_llm = _convert_iris_model_to_memiris_llm(config.sleep_tool_llm)
    json_llm = _convert_iris_model_to_memiris_llm(config.sleep_json_llm)

    return (
        MemorySleepPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_memory_connection_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .set_group_size(25)
        .set_max_threads(20)
        .set_tool_llm(tool_llm)
        .set_response_llm(json_llm)
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
        if not settings.memiris.enabled:
            logging.info("Memiris is disabled in settings.")
            self.enabled = False
            return

        if not settings.memiris.llm_configuration:
            logging.error("Memiris is enabled but LLM configuration is missing.")
            self.enabled = False
            return

        self.enabled = True

        # Create embedding models from configuration
        config = settings.memiris.llm_configuration
        self._memiris_embedding_models = [
            _convert_iris_model_to_memiris_llm(model_id)
            for model_id in config.embeddings
        ]
        self.vectorizer = Vectorizer(self._memiris_embedding_models)

        # Create pipelines using configuration
        self.memory_creation_pipeline = _create_memory_creation_pipeline(
            weaviate_client, self.vectorizer
        )
        self.memory_sleep_pipeline = _create_memory_sleep_pipeline(
            weaviate_client, self.vectorizer
        )

        self.learning_service = LearningService(weaviate_client)
        self.memory_service = MemoryService(weaviate_client)
        self.memory_connection_service = MemoryConnectionService(weaviate_client)
        self.tenant = tenant

    @observe(name="Memiris: Create Memories")
    def create_memories(self, text: str, reference: str) -> Sequence[Memory]:
        """
        Creates memories for the given text using the memory creation pipeline.

        Args:
            text (str): The text to create memories from.
            reference (str): The reference for the memories.
        Returns:
            Sequence[Memory]: A sequence of created Memory objects.
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, returning empty sequence.")
            return []
        return self.memory_creation_pipeline.create_memories(
            self.tenant, text, reference
        )

    @observe(name="Memiris: Create Memories (Async)")
    def create_memories_in_separate_thread(
        self,
        text: str,
        reference: str,
        result_storage: list[Memory],
    ) -> Thread:
        """
        Creates memories for the given text in a separate thread and stores the results in the provided storage.

        Args:
            text (str): The text to create memories from.
            reference (str): The reference for the memories.
            result_storage (list[Memory]): The storage to append the created memories to.
        Returns:
            Thread: The thread that is running the memory creation.
        """
        # Capture parent tracing context before spawning thread
        parent_ctx = get_current_context()

        def _create_memories():
            # Restore parent tracing context in child thread
            if parent_ctx:
                set_current_context(parent_ctx)
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

    @observe(name="Memiris: Sleep Memories")
    def sleep_memories(self) -> None:
        """
        Sleeps memories for the tenant using the memory sleep pipeline.
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, skipping sleep memories.")
            return
        # Track time for the sleep operation
        start_time = time.perf_counter()
        logging.info("Starting memory sleep for tenant %s", self.tenant)
        self.memory_sleep_pipeline.sleep(self.tenant)
        elapsed = time.perf_counter() - start_time
        logging.info(
            "Memory sleep finished for tenant %s; duration=%.3fs", self.tenant, elapsed
        )

    def has_memories(self) -> bool:
        """
        Checks if there are any memories for the tenant.

        Returns:
            bool: True if there are memories, False otherwise.
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, returning empty sequence.")
            return False
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
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, returning empty sequence.")
            return None
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
        # Filter out deleted memories and memories that don't exist
        connected_memory_map: dict[UUID, Memory] = {
            mem.id: mem
            for mem in connected_memories
            if mem is not None and mem.id is not None and not mem.deleted
        }

        # Build DTOs
        memory_dto = MemoryDTO.from_memory(memory)
        learning_dtos = [LearningDTO.from_learning(learning) for learning in learnings]

        connection_dtos = []
        for conn in connections:
            # Only include memories that exist and are not deleted
            filtered_memory_ids = [
                mid for mid in conn.memories if mid in connected_memory_map
            ]
            # Filter out the current memory from the connection to check if there are other memories
            other_memory_ids = [mid for mid in filtered_memory_ids if mid != memory.id]

            # Only include connection if it has at least one other valid memory besides the current one
            if len(other_memory_ids) > 0:
                connection_dtos.append(MemoryConnectionDTO.from_connection(conn))

        return MemoryWithRelationsDTO(
            memory=memory_dto, learnings=learning_dtos, connections=connection_dtos
        )


def memory_sleep_task():
    """
    A periodic task to sleep memories for all users.
    """
    if not settings.memiris.enabled or not settings.memiris.sleep_enabled:
        logging.info("Memiris memory sleep task is disabled. Skipping execution.")
        return
    logging.info("Running memory sleep task for all users.")
    vector_db = VectorDatabase().static_client_instance
    if not vector_db:
        logging.warning("Vector database client not initialized. Skipping sleep task.")
        return
    memory_service = MemoryService(vector_db)
    tenants = memory_service.find_all_tenants()
    if not tenants:
        logging.info("No tenants found in memory service. Exiting sleep task.")
        return
    tenants = [tenant for tenant in tenants if tenant.startswith("artemis-user-")]
    logging.info("Found %d tenants for memory sleep task.", len(tenants))
    tenants = [
        tenant for tenant in tenants if memory_service.has_unslept_memories(tenant)
    ]
    logging.info("Found %d tenants with unslept memories.", len(tenants))
    total = len(tenants)
    if total == 0:
        logging.info("No tenants with unslept memories found. Exiting sleep task.")
        return
    for idx, tenant in enumerate(tenants, start=1):
        try:
            logging.info("Sleeping memories for tenant %s (%d/%d)", tenant, idx, total)
            memiris_wrapper = MemirisWrapper(vector_db, tenant)
            start = time.perf_counter()
            memiris_wrapper.sleep_memories()
            elapsed = time.perf_counter() - start
            logging.info(
                "Finished sleeping memories for tenant %s (%d/%d) in %.3fs",
                tenant,
                idx,
                total,
                elapsed,
            )
        except Exception as e:
            logging.error(
                "Error sleeping memories for tenant %s: %s", tenant, e, exc_info=True
            )
