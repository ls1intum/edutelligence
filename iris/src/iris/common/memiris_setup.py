import contextvars
import logging
import os
import time
import warnings
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
from memiris.api.llm_config_service import LlmConfigService
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
from iris.tracing import observe
from iris.vector_database.database import VectorDatabase

_memiris_user_focus_personal_details = """
Find personal details about the user (e.g., name, education, proficiency level, personality).
Always start with 'The user'. Use 'they/them' pronouns unless specified.
Keep learnings atomic and concise.

CRITICAL INSTRUCTIONS:
1. DO NOT summarize the conversation content.
2. DO NOT mention specific exercise topics (e.g., "HATEOAS", "Exercise 1") unless describing the user's skill level.
3. Focus purely on the USER'S identity, skills, and personality.
4. AVOID extracting temporary states (e.g., "The user is working on X", "The user is failing").
5. Only extract details that persist beyond this conversation.

EXAMPLES OF INPUTS WITH NO EXTRACTION (Output Nothing):
- "Can you explain REST?" -> NOTHING (User goal, not personal detail)
- "I am stuck on valid_move." -> NOTHING (Temporary state)
- "The build failed." -> NOTHING (Event, not person)
- "Thank you." -> NOTHING (Chit-chat)
- "I'm working on the HATEOAS exercise and I don't understand how to link resources." -> NOTHING (Context/Confusion)
- "I feel stupid because I can't solve this." -> NOTHING (Transient emotion)
- "My professor said we should use Factory pattern." -> NOTHING (External constraint/instruction)

High quality extraction means returning NOTHING when acceptable. Do not hallucinate details to fill space.
"""

_memiris_user_focus_requirements = """
Find specific preferences the user has for HOW they want to be answered (e.g., brevity, format, tone).
Always start with 'The user'. Use 'they/them' pronouns unless specified.
Keep learnings atomic and concise.

CRITICAL INSTRUCTIONS:
1. SEPARATE STYLE FROM CONTENT. Do not extract what the user is asking about (e.g. "User wants to know about REST").
2. IGNORE standard questions. Asking "What is X?" does not mean "User prefers definitions". \
It just means they asked a question.
3. ONLY extract if the user explicitly REQUESTS a specific format, tone, or constraints.
4. IGNORE implied preferences from single interactions.

EXAMPLES OF INPUTS WITH NO EXTRACTION (Output Nothing):
- "What is HATEOAS?" -> NOTHING (Standard question)
- "Give me the solution." -> NOTHING (Standard request)
- "Why is this wrong?" -> NOTHING (Standard debugging)
- "Can you check if my implementation of the strategy pattern is correct?" -> NOTHING (Request for feedback)
- "I need to pass the security tests." -> NOTHING (External goal)
- "Why is the output not sorted?" -> NOTHING (Debugging question)

EXTRACT ONLY IF: "Don't give me code", "Explain like I'm 5", "Give me a hint, not the answer".
If the interaction is standard, output NOTHING. It is better to miss a weak signal than to extract noise.
"""

_memiris_user_focus_facts = """
Find hard, explicitly stated facts about the user (e.g., Operating System, IDE, language constraints).
Always start with 'The user'. Use 'they/them' pronouns unless specified.
Keep learnings atomic and concise.

CRITICAL INSTRUCTIONS:
1. EXTRACT ONLY EXPLICIT, PERMANENT FACTS stated by the user.
2. NO INTERPRETATION. If the user says "I think it's a Mac", do NOT extract "User uses Mac".
3. IGNORE conversation context. The fact that they are asking about Python does not mean "User uses Python" \
(they might be learning it).
4. IGNORE transient states ("I am confused", "I am working").

EXAMPLES OF INPUTS WITH NO EXTRACTION (Output Nothing):
- "My code isn't running." -> NOTHING (Transient)
- "I need to install Java." -> NOTHING (Action, not attribute)
- "I hate this exercise." -> NOTHING (Opinion)
- "I think I might switch to VS Code later." -> NOTHING (Hypothetical/future plan)
- "The tutorial uses Python 3.9." -> NOTHING (Context about material, not user)

Most messages contain NO hard facts. Outputting NOTHING is the expected behavior for 99% of messages.
"""

type Tenant = str


# Configure LLM retry parameters for Memiris to handle transient errors gracefully
LlmConfigService.configure_retry_params(
    max_attempts=5, initial_delay=1.0, backoff_factor=2.0
)


def setup_ollama_env_vars() -> None:
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
        warnings.warn("Ollama token not configured for Memiris LLM access.")


def memiris_create_user_memory_creation_pipeline_ollama(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemoryCreationPipeline:
    """
    Creates a memory creation pipeline for users using Ollama.

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


def memiris_create_user_memory_creation_pipeline_openai(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemoryCreationPipeline:
    """
    Creates a memory creation pipeline for users using OpenAI.

    This function initializes and configures a memory creation pipeline for users.
    It sets up LLM access and vector database access.
    It also adds learning extractors for personal details, requirements, and facts about the user.

    Parameters:
        weaviate_client (WeaviateClient): A client instance for interacting with the Weaviate database.
    Returns:
        MemoryCreationPipeline: The fully constructed memory creation pipeline.
    """
    llm_manager = LlmManager()
    model_to_use: OpenAIChatModel | None = None
    for model in llm_manager.entries:
        if isinstance(model, OpenAIChatModel) and model.model == "gpt-5-mini":
            model_to_use = model
            break

    if model_to_use is None:
        logging.warning(
            "No OpenAIChatModel with model 'gpt-5-mini' found in LlmManager. "
            "Using Ollama for Memiris instead."
        )
        return memiris_create_user_memory_creation_pipeline_ollama(
            weaviate_client, vectorizer
        )

    memiris_llm = OpenAiLanguageModel(
        model=model_to_use.model,
        api_key=model_to_use.api_key,
        azure=isinstance(model_to_use, AzureOpenAIChatModel),
        azure_endpoint=getattr(model_to_use, "endpoint", None),
        api_version=getattr(model_to_use, "api_version", None),
    )
    return (
        MemoryCreationPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .add_learning_extractor(
            focus=_memiris_user_focus_personal_details,
            llm_learning_extraction=memiris_llm,
        )
        .add_learning_extractor(
            focus=_memiris_user_focus_requirements, llm_learning_extraction=memiris_llm
        )
        .add_learning_extractor(
            focus=_memiris_user_focus_facts, llm_learning_extraction=memiris_llm
        )
        .add_learning_deduplicator(llm_learning_deduplication=memiris_llm)
        .set_memory_creator_langchain(llm=memiris_llm)
        .build()
    )


def memiris_create_user_memory_sleep_pipeline_ollama(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemorySleepPipeline:
    """
    Creates a memory sleep pipeline for users.

    This function initializes and configures a memory sleep pipeline for users.
    It sets up LLM access and vector database access.

    Parameters:
        weaviate_client (WeaviateClient): A client instance for interacting with the Weaviate database.
    Returns:
        MemorySleepPipeline: The fully constructed memory sleep pipeline.
    """
    return (
        MemorySleepPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_memory_connection_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .set_group_size(50)
        .set_max_threads(4)
        .build()
    )


def memiris_create_user_memory_sleep_pipeline_openai(
    weaviate_client: WeaviateClient, vectorizer: Vectorizer
) -> MemorySleepPipeline:
    """
    Creates a memory sleep pipeline for users using OpenAI.

    This function initializes and configures a memory sleep pipeline for users.
    It sets up LLM access and vector database access.

    Parameters:
        weaviate_client (WeaviateClient): A client instance for interacting with the Weaviate database.
    Returns:
        MemorySleepPipeline: The fully constructed memory sleep pipeline.
    """
    llm_manager = LlmManager()
    model_to_use: OpenAIChatModel | None = None
    for model in llm_manager.entries:
        if isinstance(model, OpenAIChatModel) and model.model == "gpt-5-mini":
            model_to_use = model
            break

    if model_to_use is None:
        logging.warning(
            "No OpenAIChatModel with model 'gpt-5-mini' found in LlmManager. "
            "Using Ollama for Memiris instead."
        )
        return memiris_create_user_memory_sleep_pipeline_ollama(
            weaviate_client, vectorizer
        )

    memiris_llm = OpenAiLanguageModel(
        model=model_to_use.model,
        api_key=model_to_use.api_key,
        azure=isinstance(model_to_use, AzureOpenAIChatModel),
        azure_endpoint=getattr(model_to_use, "endpoint", None),
        api_version=getattr(model_to_use, "api_version", None),
    )
    return (
        MemorySleepPipelineBuilder()
        .set_memory_repository(weaviate_client)
        .set_learning_repository(weaviate_client)
        .set_memory_connection_repository(weaviate_client)
        .set_vectorizer(vectorizer)
        .set_group_size(25)
        .set_max_threads(20)
        .set_tool_llm(memiris_llm)
        .set_response_llm(memiris_llm)
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
        if not settings.memiris.enabled:
            logging.info("Memiris is disabled in settings.")
            self.enabled = False
        else:
            self.enabled = True
        self._memiris_embedding_models = [
            OllamaLanguageModel("mxbai-embed-large:latest"),
            OllamaLanguageModel("nomic-embed-text:latest"),
            # OllamaLanguageModel("embeddinggemma:latest"),
            # OllamaLanguageModel("qwen3-embedding:0.6b"),
        ]
        self.vectorizer = Vectorizer(self._memiris_embedding_models)
        self.memory_creation_pipeline_ollama = (
            memiris_create_user_memory_creation_pipeline_ollama(
                weaviate_client, self.vectorizer
            )
        )
        self.memory_creation_pipeline_openai = (
            memiris_create_user_memory_creation_pipeline_openai(
                weaviate_client, self.vectorizer
            )
        )
        self.memory_sleep_pipeline_ollama = (
            memiris_create_user_memory_sleep_pipeline_ollama(
                weaviate_client, self.vectorizer
            )
        )
        self.memory_sleep_pipeline_openai = (
            memiris_create_user_memory_sleep_pipeline_openai(
                weaviate_client, self.vectorizer
            )
        )
        self.learning_service = LearningService(weaviate_client)
        self.memory_service = MemoryService(weaviate_client)
        self.memory_connection_service = MemoryConnectionService(weaviate_client)
        self.tenant = tenant

    @observe(name="Memiris: Create Memories")
    def create_memories(
        self, text: str, reference: str, use_cloud_models: bool = False
    ) -> Sequence[Memory]:
        """
        Creates memories for the given text using the memory creation pipeline.

        Args:
            text (str): The text to create memories from.
            reference (str): The reference for the memories.
            use_cloud_models (bool): Whether to use cloud models (OpenAI) or local models (Ollama).
        Returns:
            Sequence[Memory]: A sequence of created Memory objects.
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, returning empty sequence.")
            return []
        # TODO: Memiris maintainer - add LangFuse tracing inside Memiris library
        # for internal LLM calls (memory creation, consolidation, etc.)
        if use_cloud_models:
            logging.info("Creating memories for tenant %s using OpenAI", self.tenant)
            return self.memory_creation_pipeline_openai.create_memories(
                self.tenant, text, reference
            )
        else:
            logging.info("Creating memories for tenant %s using Ollama", self.tenant)
            return self.memory_creation_pipeline_ollama.create_memories(
                self.tenant, text, reference
            )

    @observe(name="Memiris: Create Memories (Async)")
    def create_memories_in_separate_thread(
        self,
        text: str,
        reference: str,
        result_storage: list[Memory],
        use_cloud_models: bool = False,
    ) -> Thread:
        """
        Creates memories for the given text in a separate thread and stores the results in the provided storage.

        Args:
            text (str): The text to create memories from.
            reference (str): The reference for the memories.
            result_storage (list[Memory]): The storage to append the created memories to.
            use_cloud_models (bool): Whether to use cloud models (OpenAI) or local models (Ollama).
        Returns:
            Thread: The thread that is running the memory creation.
        """
        # Copy contextvars so the child thread inherits the Langfuse observation stack
        ctx = contextvars.copy_context()

        def _create_memories():
            try:
                memories = self.create_memories(text, reference, use_cloud_models)
                result_storage.extend(memories)
            except Exception as e:
                logging.error(
                    "Failed to create memories in thread: %s", e, exc_info=True
                )

        thread = Thread(
            name="MemirisMemoryCreationThread",
            target=lambda: ctx.run(_create_memories),
        )
        thread.start()
        return thread

    @observe(name="Memiris: Sleep Memories")
    def sleep_memories(self, use_cloud_models: bool = False) -> None:
        """
        Sleeps memories for the tenant using the memory sleep pipeline.

        Args:
            use_cloud_models (bool): Whether to use cloud models (OpenAI) or local models (Ollama).
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, skipping sleep memories.")
            return
        # Track time for the sleep operation and log which pipeline is used
        start_time = time.perf_counter()
        # TODO: Memiris maintainer - add LangFuse tracing inside Memiris library
        # for internal LLM calls (memory creation, consolidation, etc.)
        if use_cloud_models:
            logging.info(
                "Starting memory sleep for tenant %s using OpenAI", self.tenant
            )
            self.memory_sleep_pipeline_openai.sleep(self.tenant)
        else:
            logging.info(
                "Starting memory sleep for tenant %s using Ollama", self.tenant
            )
            self.memory_sleep_pipeline_ollama.sleep(self.tenant)
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

            # Deduplicate memories before adding to storage
            existing_ids = {m.id for m in accessed_memory_storage}
            for memory in memories:
                if memory.id not in existing_ids:
                    accessed_memory_storage.append(memory)
                    existing_ids.add(memory.id)

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
                    # Deduplicate memories before adding to storage
                    existing_ids = {m.id for m in accessed_memory_storage}
                    for memory in memories:
                        if memory.id not in existing_ids:
                            accessed_memory_storage.append(memory)
                            existing_ids.add(memory.id)
                    return memories

            memories.extend(
                self.memory_service.semantic_search(
                    tenant=self.tenant,
                    vectors=memory.vectors,
                    limit=limit - len(memories),
                )
            )

            # Deduplicate memories before adding to storage
            existing_ids = {m.id for m in accessed_memory_storage}
            for memory in memories:
                if memory.id not in existing_ids:
                    accessed_memory_storage.append(memory)
                    existing_ids.add(memory.id)

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
            cm = [
                MemoryDTO.from_memory(connected_memory_map[mid])
                for mid in conn.memories
                if mid in connected_memory_map
            ]
            # Filter out the current memory from the connection to check if there are other memories
            other_memories = [m for m in cm if m.id != str(memory.id)]

            # Only include connection if it has at least one other valid memory besides the current one
            if len(other_memories) > 0:
                connection_dtos.append(MemoryConnectionDTO.from_connection(conn))

        return MemoryWithRelationsDTO(
            memory=memory_dto, learnings=learning_dtos, connections=connection_dtos
        )

    def delete_all_for_tenant(self) -> None:
        """
        Delete all memory data (memories, learnings, and connections) for the tenant
        efficiently without loading them first.

        This method deletes all memory-related data for the current tenant by directly
        deleting from the underlying repositories.
        """
        if not self.enabled:
            logging.warning("MemirisWrapper is disabled, skipping delete operation.")
            return

        logging.info("Deleting all memory data for tenant %s", self.tenant)
        try:
            # Delete all memories, learnings, and connections for the tenant
            self.memory_service.delete_all_for_tenant(self.tenant)
            self.learning_service.delete_all_for_tenant(self.tenant)
            self.memory_connection_service.delete_all_for_tenant(self.tenant)
            logging.info(
                "Successfully deleted all memory data for tenant %s", self.tenant
            )
        except Exception as e:
            logging.error(
                "Failed to delete all memory data for tenant %s: %s",
                self.tenant,
                e,
                exc_info=True,
            )
            raise


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
